# Changelog

## [0.2.0](https://github.com/matheusbuniotto/dbt-factory/compare/v0.1.0...v0.2.0) (2026-10-15)


### Features

* configurable SQL style rule (restores [#1](https://github.com/matheusbuniotto/dbt-factory/issues/1)) ([fa9ad7f](https://github.com/matheusbuniotto/dbt-factory/commit/fa9ad7ff575b864781300dc300398b5699410013))
* configurable SQL style rule, ported onto main (restores [#1](https://github.com/matheusbuniotto/dbt-factory/issues/1)) ([a527cdd](https://github.com/matheusbuniotto/dbt-factory/commit/a527cddbb72a4ec9869d98577fb2ec04c241c063))
* point dbt-factory at any local repo ([cd9757d](https://github.com/matheusbuniotto/dbt-factory/commit/cd9757dc4b9ad9b8aa610dc51db44dc42a4b2554))
* point dbt-factory at any local repo ([db3de9b](https://github.com/matheusbuniotto/dbt-factory/commit/db3de9b95a509b72a426cc778cfb6bd8bd4b338f))


### Bug Fixes

* **api:** treat a missing optional CLI (gh) as unavailable instead of a 500 ([b296582](https://github.com/matheusbuniotto/dbt-factory/commit/b296582c0314afa9f46836450b575e3db891aa98))
* **ci:** close file handles and exempt one long pushed header ([34cfa79](https://github.com/matheusbuniotto/dbt-factory/commit/34cfa79ae26aca4dc3d7a2f06a03ac99936f9787))
* **ci:** first-party import classification independent of local checkouts; explicit allowed-root guard ([055c3d9](https://github.com/matheusbuniotto/dbt-factory/commit/055c3d9150a3db937a9441d8b3bab60ec7b648c1))
* **ci:** portable mcp smoke paths, writable runtime dirs in image, untainted eval result lookup ([a356e03](https://github.com/matheusbuniotto/dbt-factory/commit/a356e036bb5a09d99f0b56a26c9b56dcb785d82e))
* **ci:** start without a cloned project; diff-cover advisory for bulk PRs ([dadc8b8](https://github.com/matheusbuniotto/dbt-factory/commit/dadc8b85711e7d592e800acc44fedd066c97908f))
* **mock:** indent sql-mode write block ([a59980b](https://github.com/matheusbuniotto/dbt-factory/commit/a59980b9c80099b1db14e930046922230691a8c1))
* **security:** resolve CodeQL findings and make CI gates pass ([cd3415d](https://github.com/matheusbuniotto/dbt-factory/commit/cd3415dae71ba4ea003f8d18463f4fbbcb88a490))


### CI

* add portfolio-grade multi-stage GitHub Actions pipeline ([f78c3f9](https://github.com/matheusbuniotto/dbt-factory/commit/f78c3f9978d7a3bd9166cd958bf4736cf2696380))
* exempt the pushed merge commit header from commitlint ([cd2bec5](https://github.com/matheusbuniotto/dbt-factory/commit/cd2bec5da31077ea22fd2eb7d0c598f767824404))
* portfolio-grade multi-stage GitHub Actions pipeline ([8103f72](https://github.com/matheusbuniotto/dbt-factory/commit/8103f7289e37e0e8a925eadb0222ef49d8e34511))
