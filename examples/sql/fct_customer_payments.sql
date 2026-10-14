with orders as (
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
