# media_catalog

Reconciles wanted Sonarr/Radarr catalog entries from `media_catalog.enc.yaml`.

The catalog is authoritative and uses stable upstream IDs, not fuzzy titles.
Sonarr entries use `tvdb_id`; Radarr entries use `tmdb_id` or `imdb_id`.
The role adds missing catalog items, reconciles root folder, quality profile,
monitoring, and tags, then triggers app rescans so media already present under
`/data/media` is linked after a container rebuild.

This role deliberately does not import unmanaged disk folders. Validation fails
when live media paths are not represented by the encrypted catalog.
