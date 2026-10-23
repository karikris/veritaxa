// Client — attach your data to the identification at the moment of a sensitive action.
// `tag` is free-form context; `linkedId` groups related events. Both are optional.
import { useVisitorData } from '@fingerprint/react'

export function CheckoutButton({ userId, orderId }) {
  const { getData, isLoading } = useVisitorData({ immediate: false })

  async function onCheckout() {
    const { event_id } = await getData({
      tag: { action: 'checkout', orderId },
      linkedId: `user_${userId}`, // opaque id only — never an email/token
    })

    // Send the event_id to your backend; the tag + linkedId travel with the event server-side.
    await fetch('/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ eventId: event_id, orderId }),
    })
  }

  return <button onClick={onCheckout} disabled={isLoading}>Pay</button>
}
