with orders as (
    select * from {{ ref('orders') }}
)

select
    order_date,
    status,
    count(*) as order_count,
    sum(amount) as amount
from orders
group by 1, 2
