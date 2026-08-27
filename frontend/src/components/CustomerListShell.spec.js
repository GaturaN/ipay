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
  it('offers no link by default, so the field app stays a one-screen app', () => {
    expect(deskLink(shell()).exists()).toBe(false)
  })

  it('links to the iPay dashboard when the page asks for it', () => {
    const link = deskLink(shell({ deskLink: true }))
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('Back to Desk')
  })

  it('hides the link in an installed app, which has no way back out of scope', () => {
    isStandalone.mockReturnValueOnce(true)
    expect(deskLink(shell({ deskLink: true })).exists()).toBe(false)
  })

  it('keeps the desk link out of the way of the page title', () => {
    // Three items in one row: without these the longest title wraps on a narrow screen.
    const wrapper = shell({ deskLink: true })
    expect(wrapper.get('h1').classes()).toEqual(expect.arrayContaining(['min-w-0', 'truncate']))
    expect(deskLink(wrapper).element.parentElement.className).toContain('shrink-0')
  })
})
