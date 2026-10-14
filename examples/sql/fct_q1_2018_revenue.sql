with orders as (
    select * from {{ ref('orders') }}
)

select
    status,
    sum(amount) as revenue,
    count(*) as order_count
from orders
where order_date >= '2018-01-01' and order_date < '2018-03-31'
group by 1
