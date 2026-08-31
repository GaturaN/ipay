import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/data/collection', () => ({
  paymentState: vi.fn(),
  promptMpesa: vi.fn(async () => ({ status: 'sent', request: 'REQ-1' })),
  promptRequestMpesa: vi.fn(async () => ({ status: 'sent', request: 'REQ-1' })),
  saveCustomerContact: vi.fn(async () => ({})),
}))

import { paymentState } from '@/data/collection'
import PromptDialog from '@/components/PromptDialog.vue'

const POLL_MS = 3000

// What the server sends while nothing has happened yet.
const WAITING = { status: 'Pending', paid: false, partial: false, failed: false, detail: '' }

// A frappe-ui FormControl stub that still binds v-model, so the number can be typed.
const FormControl = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

async function promptAndPoll(states) {
  paymentState.mockReset()
  states.forEach((s) => paymentState.mockResolvedValueOnce(s))
  paymentState.mockResolvedValue(states[states.length - 1])

  const wrapper = mount(PromptDialog, {
    props: { target: { name: 'REQ-1', title: 'INV-1', amount: 100, kind: 'request' } },
    global: { stubs: { BaseDialog: { template: '<div><slot /></div>' }, FormControl } },
  })
  await wrapper.find('input').setValue('0712345678')
  await wrapper.findAll('button').at(-1).trigger('click')
  await vi.waitFor(() => expect(paymentState).not.toHaveBeenCalled())

  for (let i = 0; i < states.length; i += 1) {
    await vi.advanceTimersByTimeAsync(POLL_MS)
  }
  return wrapper
}

describe('PromptDialog — a payment that arrived but was not recorded', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('tells the collector to stop, rather than that the customer has not paid', async () => {
    const wrapper = await promptAndPoll([{ ...WAITING, status: 'Received', received: true }])
    expect(wrapper.text()).toContain('Payment received')
    expect(wrapper.text()).toContain('Do not charge again')
    // The exact sentence that invited the second charge in the real incident.
    expect(wrapper.text()).not.toContain('it will reflect once the customer pays')
  })

  it('stops polling once the money has arrived, so the message cannot be overwritten', async () => {
    await promptAndPoll([{ ...WAITING, status: 'Received', received: true }])
    const callsAtSettle = paymentState.mock.calls.length
    await vi.advanceTimersByTimeAsync(POLL_MS * 5)
    expect(paymentState.mock.calls.length).toBe(callsAtSettle)
  })

  it('re-enables nothing that would let the collector charge again by accident', async () => {
    // The prompt button releases on any settled outcome (that is existing behaviour), so the
    // message is what has to carry the warning — and the server refuses a repeat anyway.
    const wrapper = await promptAndPoll([{ ...WAITING, status: 'Received', received: true }])
    expect(wrapper.text()).toContain('Do not charge again')
  })

  it('still shows the ordinary outcomes it always did', async () => {
    const paid = await promptAndPoll([{ ...WAITING, status: 'Success', paid: true, detail: 'ref' }])
    expect(paid.text()).toContain('Payment received')

    const failed = await promptAndPoll([
      { ...WAITING, status: 'Failed', failed: true, detail: 'Wrong PIN' },
    ])
    expect(failed.text()).toContain('Wrong PIN')
  })

  it('falls back to "still waiting" only while nothing has actually happened', async () => {
    const wrapper = await promptAndPoll(Array.from({ length: 40 }, () => ({ ...WAITING })))
    expect(wrapper.text()).toContain('Still waiting')
  })
})
