import { describe, expect, it } from 'vitest'
import { Decoder, Encoder, PacketType } from 'socket.io-parser'

// main.js does `app.use(FrappeUI)` with no options, and frappe-ui defaults
// socketio:true, so this decoder reads every realtime frame the app receives.
// Nothing in src/ imports it, so without these tests a parser bump lands unseen.

const NAMESPACE = '/site'

function decode(frames) {
  const decoder = new Decoder()
  const packets = []
  decoder.on('decoded', (packet) => packets.push(packet))
  frames.forEach((frame) => decoder.add(frame))
  return { decoder, packets }
}

describe('socket.io-parser on the realtime receive path', () => {
  it('decodes the shape Frappe actually sends', () => {
    // frappe/realtime JSON.parse()s every payload off Redis before emitting, so
    // server frames are always plain string EVENT packets with no attachments.
    const { packets } = decode([`2${NAMESPACE},["list_update",{"doctype":"Sales Invoice"}]`])

    expect(packets).toHaveLength(1)
    expect(packets[0].type).toBe(PacketType.EVENT)
    expect(packets[0].data).toEqual(['list_update', { doctype: 'Sales Invoice' }])
  })

  it('rejects a binary packet that declares zero attachments', () => {
    const decoder = new Decoder()

    expect(() => decoder.add(`50-${NAMESPACE},["evt",{}]`)).toThrow(/Illegal attachments/)
  })

  it('keeps no reconstructor state after rejecting that packet', () => {
    // The leak this guards: a retained reconstructor waits for zero buffers
    // forever, so every binary frame after it is held rather than dispatched.
    const decoder = new Decoder()
    try {
      decoder.add(`50-${NAMESPACE},["evt",{}]`)
    } catch {
      // expected — the assertion is about what the decoder keeps afterwards
    }
    const packets = []
    decoder.on('decoded', (packet) => packets.push(packet))

    expect(decoder.reconstructor).toBeFalsy()

    decoder.add(`2${NAMESPACE},["pong"]`)
    expect(packets).toHaveLength(1)
  })

  it('declares an attachment count matching the buffers it emits', () => {
    // hasBinary() honours toJSON(), so the encoder must too or it writes a
    // header whose count does not match the binary frames that follow it.
    const payload = { toJSON: () => ({ thumb: new Uint8Array([1, 2, 3]) }) }

    const [header, ...buffers] = new Encoder().encode({
      type: PacketType.EVENT,
      nsp: NAMESPACE,
      data: ['evt', payload],
    })
    const declared = Number(String(header).match(/^5(\d+)-/)?.[1] ?? -1)

    expect(declared).toBe(buffers.length)
    expect(declared).toBeGreaterThan(0)
  })
})
