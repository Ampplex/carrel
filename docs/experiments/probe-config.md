# Probe: live service capabilities

Run: `2026-08-13T18:05:49+00:00`

SDK version: `0.1.41` · namespace `carrel-probe`

| Setting | Value |
|---|---|
| async_pending_count | 0 |
| async_worker_running | True |
| async_write_enabled | True |
| chat_model | mistral.mistral-large-2407-v1:0 |
| embedding_dim | 1024 |
| geo_enrichment_enabled | True |
| image_retention_days | indefinite |
| image_retention_enabled | True |
| multimodal_image_search_enabled | True |
| neo4j_connected | True |
| provider | bedrock |
| vision_enabled | True |

### What this project needs

- **vision_enabled: on** — needed for photo questions at all
- **image_retention_enabled: on** — needed for re-reading a photo later — the whole pillar
- **multimodal_image_search_enabled: on** — needed for finding a photo by how it looks
- **async_write_enabled: on** — needed for the settling tray has something to show

Everything this project relies on is live.
