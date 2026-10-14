with customers as (
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
