Add refunds to the order workflow. `Workflow.refund(order, on)` refunds a paid or shipped order:

- The order's status becomes a new `OrderStatus.REFUNDED` (value `"refunded"`), and an `order.refunded` event is published with the payload `{"id": order.id}`, like the other status moves.
- The ledger gets one balanced transaction dated `on`, with the memo `refund <order id>` (for example `refund o1`), that reverses the order's sale: it debits `revenue` and `tax_payable` and credits `cash`, one leg per account, with exactly the amounts the sale was recorded with when the order was paid. That must hold even if a coupon has expired since, the coupon book has changed since, or the refund is made through a different `Workflow` on the same `Ledger`. After a sale and its refund, the `cash`, `revenue` and `tax_payable` balances are back where they were before the sale.

Refunding an order in any other status raises `ValidationError` and changes nothing: no status change, no event, no ledger entry. A refunded order cannot move to any other status. Refunded orders save to and load from a `Repository` like any other order.
