# Azure preparation plan — Phase 0

Status: Executing local integration preparation; cloud deployment not started.
Date: November 14, 2026.

## Scope and authorization

The user approved Phase 0 of `docs/GAMEPLAN.md` with “proceed on working on phase 0.” That approval covers the existing integration-spike plan: local app verification, a model check, a Cosmos test-record round trip, and Photon send/reply verification when credentials and an opted-in recipient are available. It does not select an Azure subscription, region, SKU, or authorize an unreviewed cloud deployment.

## Requirements and components

Hackathon development POC, single board, small scale, cost-conscious. Existing components: React/Vite frontend, Python FastAPI API, planned Python worker, Cosmos DB for NoSQL. No provider credentials or Azure CLI were detected during the initial check.

## Recipe and target

Local SDK spike against an existing Cosmos account first. Deployment preparation can later use AZD with Bicep after subscription/region are known. Proposed hosting: Azure Container Apps for API/worker/optional Photon bridge, Static Web Apps for the built frontend, managed identity for Cosmos, and Microsoft Entra ID for dashboard identity. These are proposed choices; no resources are provisioned by Phase 0 scripts.

Subscription: not configured. Region: not selected. Budget/SKU: not selected. Public callback: unavailable until a hosted endpoint is assigned.

## Checklist

- [x] Inspect repository and approved Phase 0 scope.
- [x] Inspect credential presence without printing secrets.
- [x] Research current Cosmos SDK and messaging contract.
- [ ] Verify local API and frontend proxy.
- [ ] Add optional SDK smoke checks and explicit mock fallbacks.
- [ ] Run real Cosmos test-record round trip when account access is provided.
- [ ] Confirm subscription/region before infrastructure generation.
- [ ] Run azure-validate before any future cloud deployment.

## Research summary

Cosmos Python SDK uses a CosmosClient, database/container clients, and point reads with an explicit partition key. Winnie uses `/board_id`; the spike checks the existing container's partition definition before creating a synthetic item. Prefer managed identity for deployment; account keys are accepted only server-side for the local spike.

Sources: https://learn.microsoft.com/en-us/azure/cosmos-db/quickstart-python and `docs/PHASE0.md` (integration evidence and remaining blockers).

## Validation proof

No cloud validation or deployment has occurred. Local verification results are tracked in `docs/PHASE0.md`.
