# Tally / Excel import formats

Three CSV exports feed the inventory-based shortfall check. Upload each as
`{"filename": ..., "csv_content": ...}` (API key required):

| File | Endpoint |
| --- | --- |
| `stock_summary.csv` | `POST /api/v1/ingest/stock-summary` |
| `open_purchase_orders.csv` | `POST /api/v1/ingest/open-purchase-orders` |
| `sales_order_lines.csv` | `POST /api/v1/ingest/sales-order-lines` |

Each response is `{success, filename, imported_count, errors, warnings}`. Valid rows are imported even when
other rows fail; every failed row is listed in `errors` as `{line, error}` (line 1 is the header). `warnings` (`{line, warning}`) cover rows that are skipped or imported with a caveat: stock-summary total rows, overdue POs, and re-imported POs that are no longer OPEN (their status is kept). Warnings about rows the file does *not* contain (see below) have `line: null`.

## Each file is a full snapshot

Export the whole report every time, not just the changes. An import replaces what it covers:

| File | What a missing row means |
| --- | --- |
| Stock summary | The item's stock is **set to 0** (Tally hides zero-balance items, so a missing item ran out), with the warning "ITEM not in file — stock set to 0". The shortfall check then uses 0, not an old number. |
| Open purchase orders | An OPEN PO that is not in the file is marked **CLOSED** (received or cancelled) and no longer counted as inbound. This stops a received PO from being counted twice: once in stock and once as inbound. |
| Sales order lines | For each order the file lists, the file replaces all of that order's lines: a line of that order not in the file is **removed**. Orders the file does not list are untouched. |

Every zeroing, removal or closure is listed in `warnings`. A row with an error is left as it was (it is not changed),
and a file whose header cannot be read changes nothing.

## Columns (case-insensitive; any alias works)

- Item code: `item_code`, `Item Code`, `Stock Item Code`
- Item name: `item_name`, `Item Name`, `Name of Item` (stock summary only; creates the item if its code is new)
- Quantity, per file, in priority order (when a file has several of these columns, the first one listed wins):
  - stock summary: `on_hand_qty`, `Closing Quantity`, `Quantity`, `Qty`
  - open purchase orders: `Pending Quantity`, `Pending Qty`, `Quantity`, `Qty` (a pending-PO export with both
    the ordered `Quantity` and the `Pending Quantity` imports the pending part: only that is still inbound)
  - sales order lines: `Qty`, `Quantity`
- Unit: `Unit`, `UOM` (stock summary only; the unit of an item the file creates. Without the column a new
  item gets `pcs`. The unit of an existing item is not changed.)
- PO / shipment id: `shipment_id`, `PO Number`, `Voucher No`
- Supplier: `supplier_id`, `Supplier Code`, `Party Code`
- Due date: `eta`, `Due Date`, `Due on`
- Order: `order_id`, `Order No`, `Sales Order No`

## Values

- Quantities are digits with optional thousands separators (`1,200`, `1,20,000`), optionally followed by
  one unit word (`500 Nos`, `500 pcs`). Negative, empty or other text is a row error. PO and order-line
  quantities must be above zero; stock may be zero.
- Dates: `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY` or Tally style `20-Nov-2026`, with an optional `HH:MM`.
  Times are IST. A date alone means 17:00 IST.
- An unknown supplier, item or order is a row error, and so is a repeated id within one file
  (a repeated PO number, item code, or order + item pair).

## Demo samples

The samples reproduce the demo seed data: stock `CASING` 350; PO `SHP-CHN-0001` for 500 from
`SUP-CHN-01`; order lines `EV-402` 500 and `EV-405` 300.

The PO is meant to arrive "tomorrow". **Edit the Due Date in `open_purchase_orders.csv` to a near-future
date before importing**: an open PO whose due date is already past is still imported but reported in `warnings` as overdue, and the shortfall calculation does not count it as inbound.
