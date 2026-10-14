select item_id, category, price from {{ ref('raw_items') }}
