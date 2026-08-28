import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

// The link is offered in a browser tab but not in an installed app, so the device check is
// the one behaviour worth controlling here.
vi.mock('@/utils/device', () => ({
  isStandalone: vi.fn(() => false),
  isMobileOrTablet: vi.fn(() => false),
  getPlatform: vi.fn(() => 'other'),
}))

// The bell pulls in frappe-ui (and its icon virtual modules) and the tour pulls in driver.js
// and the session store. Neither has anything to do with the header link.
vi.mock('@/components/NotificationSettings.vue', () => ({
  default: { name: 'NotificationSettings', template: '<div />' },
}))
vi.mock('@/composables/useTour', () => ({ useFirstRunTour: () => {} }))

import { isStandalone } from '@/utils/device'
import CustomerListShell from '@/components/CustomerListShell.vue'

const DESK_URL = '/app/ipay'

// shallow: the cards, the cheque banner and the retry pane are irrelevant to the header.
const shell = (props = {}) =>
  mount(CustomerListShell, {
    props: { title: 'Collect Payments', ...props },
    shallow: true,
  })

const deskLink = (wrapper) => wrapper.find(`a[href="${DESK_URL}"]`)

describe('CustomerListShell — back to the desk', () => {
  it('offers no link unless a page asks for one', () => {
    expect(deskLink(shell()).exists()).toBe(false)
  })

  it('links to the iPay dashboard when a page asks for it', () => {
    const link = deskLink(shell({ showDeskLink: true }))
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('Back to Desk')
  })

  it('accepts the bare attribute the pages actually write', () => {
    // The pages write `show-desk-link` with no value. Passing the prop object directly, as
    // the tests above do, would not catch Vue failing to cast that to true.
    const parent = {
      components: { CustomerListShell },
      template: '<CustomerListShell title="Collect Payments" show-desk-link />',
    }
    // router-link is registered by the app's router, not by a bare mount.
    const wrapper = mount(parent, { global: { stubs: { 'router-link': true } } })
    expect(deskLink(wrapper).exists()).toBe(true)
  })

  it('hides the link in an installed app, which has no way back out of scope', () => {
    isStandalone.mockReturnValueOnce(true)
    expect(deskLink(shell({ showDeskLink: true })).exists()).toBe(false)
  })

  it('keeps the desk link out of the way of the page title', () => {
    // Three items in one row: without these the longest title wraps on a narrow screen.
    const wrapper = shell({ showDeskLink: true })
    expect(wrapper.get('h1').classes()).toEqual(expect.arrayContaining(['min-w-0', 'truncate']))
    expect(deskLink(wrapper).element.parentElement.className).toContain('shrink-0')
  })
})

describe('the pages the desk links into', () => {
  // Every page /collect_payments can redirect to needs the way back, or the round trip is
  // one-way for that persona. Asserted against the sources because mounting a page pulls in
  // frappe-ui, whose source ESM does not resolve outside a Vite build.
  it.each(['Collect', 'InternalCollect', 'SalesCollect'])('%s opts in', (page) => {
    // Relative to the vitest root (frontend/), not to this file: under Vite,
    // import.meta.url is a served URL rather than a filesystem path.
    const src = readFileSync(`src/pages/${page}.vue`, 'utf8')
    expect(src).toContain('show-desk-link')
  })
})
