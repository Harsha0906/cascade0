# Tally / Excel import formats

Three CSV exports feed the inventory-based shortfall check. Upload each as
`{"filename": ..., "csv_content": ...}` (API key required):

| File | Endpoint |
| --- | --- |
| `stock_summary.csv` | `POST /api/v1/ingest/stock-summary` |
| `open_purchase_orders.csv` | `POST /api/v1/ingest/open-purchase-orders` |
| `sales_order_lines.csv` | `POST /api/v1/ingest/sales-order-lines` |

Each response is `{success, filename, imported_count, errors, warnings}`. Valid rows are imported even when
other rows fail; every failed row is listed in `errors` as `{line, error}` (line 1 is the header). `warnings` (`{line, warning}`) cover rows that are skipped or imported with a caveat: stock-summary total rows, overdue POs, and re-imported POs that are no longer OPEN (their status is kept).

## Columns (case-insensitive; any alias works)

- Item code: `item_code`, `Item Code`, `Stock Item Code`
- Item name: `item_name`, `Item Name`, `Name of Item` (stock summary only; creates the item if its code is new)
- Quantity: `on_hand_qty`, `Closing Quantity`, `Quantity`, `Pending Quantity`, `Qty`
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
