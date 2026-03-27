# Frontend Routing And View Ownership Contract v1

Status: AUTHORITATIVE

Purpose: Defines route and view ownership in `ncc-frontend/app/`.

## 1) Route-Level Ownership

- route modules own navigation and page composition
- route modules do not own lifecycle rules
- route modules may initiate backend reads and actions through approved client layers

## 2) View Ownership Areas

- shell or authenticated layout
- game selection and onboarding
- dashboard and inventory
- instance detail
- logs and events
- settings and administration

## 3) Rules

- page composition may aggregate view components
- component composition must not create hidden action flows
- view code may derive display state only
