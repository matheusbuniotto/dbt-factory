select category, sum(price) as revenue from {{ ref('stg_items') }} group by 1
