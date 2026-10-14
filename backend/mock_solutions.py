"""Canned mock solutions keyed by prompt. Some are intentionally flawed so evals fail realistically."""
import re

SOLUTIONS = []

def solution(pattern, model, sql, yml, plan, summary, waivers=None, followup=None):
    SOLUTIONS.append({"re": re.compile(pattern, re.I), "model": model, "sql": sql, "yml": yml, "plan": plan,
                      "summary": summary, "waivers": waivers or {}, "followup": followup})

# 1) correct monthly revenue (default)
solution(r"monthly revenue|revenue mart", "fct_monthly_revenue",
"""with orders as (
    select * from {{ ref('orders') }}
)

select
    date_trunc('month', order_date) as order_month,
    count(distinct order_id) as order_count,
    count(distinct customer_id) as customer_count,
    sum(amount) as revenue,
    round(sum(amount) / count(distinct order_id), 2) as avg_order_value
from orders
group by 1
""",
"""version: 2
models:
  - name: fct_monthly_revenue
    description: Monthly orders, customers, revenue and AOV.
    config:
      meta:
        grain: [order_month]
    columns:
      - name: order_month
        description: First day of the order month.
        data_tests: [unique, not_null]
      - name: order_count
        description: Distinct orders in the month.
        data_tests: [not_null]
      - name: customer_count
        description: Distinct ordering customers.
      - name: revenue
        description: Sum of order amount.
        data_tests: [not_null]
      - name: avg_order_value
        description: revenue / order_count.
""",
"- Read `orders` mart\n- Add `fct_monthly_revenue` at month grain\n- Document + test grain\n- Build, profile, run Definition of Done",
"fct_monthly_revenue: grain order_month, revenue reconciles with orders.amount.",
waivers={"reconciles": "new model; reconciled manually against sum(orders.amount)"})

# 2) FAN-OUT TRAP: customer payments, naive join inflates order counts
solution(r"customer.*(payment|paid)|payments per customer|fan.?out", "fct_customer_payments",
"""with orders as (
    select * from {{ ref('stg_orders') }}
),

payments as (
    select * from {{ ref('stg_payments') }}
)

select
    orders.customer_id,
    count(orders.order_id) as number_of_orders,
    sum(payments.amount) as total_paid
from orders
left join payments on orders.order_id = payments.order_id
group by 1
""",
"""version: 2
models:
  - name: fct_customer_payments
    description: One row per customer with orders and total paid.
    columns:
      - name: customer_id
        description: Customer key.
        data_tests: [unique, not_null]
      - name: number_of_orders
        description: Orders placed.
      - name: total_paid
        description: Sum of payments.
""",
"- Join stg_orders to stg_payments\n- Aggregate per customer\n- Test customer_id grain",
"fct_customer_payments built (one row per customer).")

# 3) grain ambiguity: daily orders by status (composite grain declared)
solution(r"daily.*status|orders by status per day|status per day", "fct_daily_orders_by_status",
"""with orders as (
    select * from {{ ref('orders') }}
)

select
    order_date,
    status,
    count(*) as order_count,
    sum(amount) as amount
from orders
group by 1, 2
""",
"""version: 2
models:
  - name: fct_daily_orders_by_status
    description: Orders and amount per day and status.
    config:
      meta:
        grain: [order_date, status]
    columns:
      - name: order_date
        description: Order date.
        data_tests: [not_null]
      - name: status
        description: Order status.
        data_tests:
          - not_null
          - accepted_values:
              arguments:
                values: ['placed', 'shipped', 'completed', 'return_pending', 'returned']
      - name: order_count
        description: Orders.
      - name: amount
        description: Amount.
""",
"- Grain is (order_date, status)\n- Declare meta.grain\n- accepted_values on status",
"fct_daily_orders_by_status at (order_date, status) grain.",
waivers={"reconciles": "new model; totals equal orders.amount"})

# 4) NULL HANDLING: customers with no orders should have 0 LTV — mock forgets coalesce
solution(r"lifetime value|ltv|no orders.*0", "dim_customer_ltv",
"""with customers as (
    select * from {{ ref('stg_customers') }}
),

orders as (
    select * from {{ ref('orders') }}
),

ltv as (
    select
        customer_id,
        sum(amount) as lifetime_value
    from orders
    group by 1
)

select
    customers.customer_id,
    customers.first_name,
    ltv.lifetime_value
from customers
left join ltv on customers.customer_id = ltv.customer_id
""",
"""version: 2
models:
  - name: dim_customer_ltv
    description: Customer lifetime value.
    columns:
      - name: customer_id
        description: Customer key.
        data_tests: [unique, not_null]
      - name: first_name
        description: First name.
      - name: lifetime_value
        description: Sum of order amounts.
""",
"- Aggregate orders per customer\n- Left join to customers",
"dim_customer_ltv built.")

# 5) MONTH BOUNDARY: Q1 revenue — mock uses < '2018-03-31' (excludes Mar 31)
solution(r"q1|first quarter|jan.*mar", "fct_q1_2018_revenue",
"""with orders as (
    select * from {{ ref('orders') }}
)

select
    status,
    sum(amount) as revenue,
    count(*) as order_count
from orders
where order_date >= '2018-01-01' and order_date < '2018-03-31'
group by 1
""",
"""version: 2
models:
  - name: fct_q1_2018_revenue
    description: Q1 2018 revenue by status.
    config:
      meta:
        grain: [status]
    columns:
      - name: status
        description: Order status.
        data_tests: [unique, not_null]
      - name: revenue
        description: Revenue.
      - name: order_count
        description: Orders.
""",
"- Filter Q1 2018\n- Revenue by status",
"fct_q1_2018_revenue built.",
waivers={"reconciles": "new model"})

# 6) status summary with is_returned flag (correct)
solution(r"is_returned|returned flag|status summary", "fct_order_status_summary",
"""with orders as (
    select * from {{ ref('orders') }}
)

select
    status,
    status in ('returned', 'return_pending') as is_returned,
    count(*) as order_count,
    sum(amount) as amount
from orders
group by 1, 2
""",
"""version: 2
models:
  - name: fct_order_status_summary
    description: Orders and amount per status with return flag.
    config:
      meta:
        grain: [status]
    columns:
      - name: status
        description: Order status.
        data_tests: [unique, not_null]
      - name: is_returned
        description: True for returned / return_pending.
        data_tests: [not_null]
      - name: order_count
        description: Orders.
      - name: amount
        description: Amount.
""",
"- Group by status\n- Add is_returned flag",
"fct_order_status_summary built.",
waivers={"reconciles": "new model; totals equal orders"})

# 7) STYLE TRAP: correct data, sloppy SQL style (uppercase keywords, bare JOIN, implicit alias)
solution(r"payment method", "fct_payment_methods",
"""WITH payments AS (
    SELECT * FROM {{ ref('stg_payments') }}
)

SELECT
    p.payment_method,
    COUNT(DISTINCT p.order_id) AS order_count,
    SUM(p.amount) total_amount
FROM payments p
GROUP BY 1
""",
"""version: 2
models:
  - name: fct_payment_methods
    description: Orders and amount per payment method.
    config:
      meta:
        grain: [payment_method]
    columns:
      - name: payment_method
        description: Payment method.
        data_tests: [unique, not_null]
      - name: order_count
        description: Distinct orders paid with the method.
      - name: total_amount
        description: Sum of payment amount.
""",
"- Aggregate stg_payments by payment_method\n- Test grain",
"fct_payment_methods built (one row per payment method).",
waivers={"reconciles": "new model; totals equal stg_payments"})

def pick(prompt):
    for s in SOLUTIONS:
        if s["re"].search(prompt or ""): return s
    return SOLUTIONS[0]
