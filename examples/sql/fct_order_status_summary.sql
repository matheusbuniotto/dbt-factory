with orders as (
    select * from {{ ref('orders') }}
)

select
    status,
    status in ('returned', 'return_pending') as is_returned,
    count(*) as order_count,
    sum(amount) as amount
from orders
group by 1, 2
