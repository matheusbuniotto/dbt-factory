select
    order_date,
    sum(amount) as revenue
from analytics.orders
group by order_date
