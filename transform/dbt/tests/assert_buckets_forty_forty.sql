-- The registered split is 40 price-visible and 40 price-opaque. Fails if either
-- side is any other size.
--
-- docs/preregistration.md commits to an assignment that is not edited to improve
-- a result. A seed is an editable text file, so that promise needs something
-- enforcing it: silently dropping the four items that turned out inconvenient
-- would leave no trace anywhere else in the build.
--
-- If a genuine coverage fault requires a pattern to change, the item is replaced
-- and the count holds. If the count itself must change, that is a new
-- registration and this test should fail until the doc says so.

select
    bucket,
    count(*) as n_items
from {{ ref('buckets') }}
group by bucket
having count(*) <> 40
