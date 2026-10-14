with orders as (
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
