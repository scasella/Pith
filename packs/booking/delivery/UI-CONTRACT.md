# Booking UI contract (pith.booking)

Frozen. The affordances the judge drives in a real browser (`delivery/browser_workflows.py`). Everything else about
the page (layout, framework, wording, styling, how time is shown) is the candidate's. The judge never reads the
page's own ids or text to decide an outcome when an attribute below says it; it reads the service's state through
the frozen client.

## Affordances (`data-testid`)

| testid | Element | Meaning |
|---|---|---|
| `resource-id`, `resource-name` | inputs | the id (integer) and name of a resource to create |
| `resource-create` | button | create it (POST /resources); the page then shows that resource |
| `resource-pick` | input | the id of a resource to show |
| `resource-load` | button | show the resource in `resource-pick` |
| `calendar` | element | the shown calendar; `data-resource-id` is the id of the resource whose bookings are shown |
| `book-start`, `book-end` | inputs | a time of day as `HH:MM` (24-hour) on the contract's abstract day: minute = 60·HH + MM |
| `book-submit` | button | book `[start, end)` on the shown resource, with a request id the page chooses |
| `booking-row` | element, one per booking shown | `data-booking-id`, `data-start`, `data-end` (minutes), `data-active` (`true`/`false`); cancelled bookings may be omitted instead |
| `cancel` | button inside a `booking-row` | cancel that row's booking |
| `move-start`, `move-end`, `move-submit` | inputs and button inside a `booking-row` | reschedule that row's booking to `[start, end)` (`HH:MM`) |
| `receipt` | element | the result of the last book, move or cancel the page submitted, until the next one |

`receipt` carries `data-outcome`: `ACCEPTED`, `CONFLICT`, `INVALID` or `NOT_ACTIVE` (the service's outcome),
`CANCELLED` or `NOT_CANCELLED` (a cancel's result), `UNKNOWN` (no response arrived: the operation may or may not have
happened) or `ERROR` (the service answered with an error status). It also carries `data-booking-id` and
`data-resource-id` (the booking and resource the operation was about) and, for a conflict, `data-conflicts-with`.

## Workflows

BW1–BW6 (`delivery.yaml`) are driven at desktop and mobile widths. Each is judged from the service's state and the
attributes above: a booking that the page says was accepted must exist in the service with that interval; a
conflict must name a booking that really overlaps; a refused move must leave the row and the service unchanged.

## Interaction obligations

Judged at desktop width with faults the judge injects into the page's own requests (Playwright request
interception; the page under test is unmodified):

- **BI1 receipt preservation**: after an accepted booking, the page's next refresh of the calendar fails. The
  receipt still says `ACCEPTED` for that booking; it is not replaced by an error.
- **BI2 outcome/view separation**: the service commits a booking but its response never reaches the page. The
  receipt says `UNKNOWN`, not `CONFLICT`, `INVALID` or `ERROR`; the page does not claim the booking failed.
- **BI3 action-target binding**: with several rows shown, `cancel` and `move-submit` in a row act on that row's
  booking (by its id), and on no other.
