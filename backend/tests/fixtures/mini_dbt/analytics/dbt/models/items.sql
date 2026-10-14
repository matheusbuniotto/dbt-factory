select item_id, category, price, price > 8 as is_premium from {{ ref('stg_items') }}
