// Server — verify the event first, then read back the tag/linkedId you set on the client.
// Only trust the tag after the event itself verifies (see fingerprint-node verifyEvent).
const { fingerprint } = require('./client')

async function readTaggedEvent(eventId) {
  const event = await fingerprint.getEvent(eventId)
  if (!event.identification?.visitor_id) return { ok: false, reason: 'not_found' }

  const tag = event.tags ?? {} // the JSON you passed to getData({ tag }) — server field is `tags`
  const linkedId = event.linked_id ?? null // the string you passed to getData({ linkedId })

  // Example: confirm the order the client claims matches the tagged order.
  // if (tag.orderId !== expectedOrderId) return { ok: false, reason: 'order_mismatch' }

  return { ok: true, visitorId: event.identification.visitor_id, tag, linkedId }
}

module.exports = { readTaggedEvent }
