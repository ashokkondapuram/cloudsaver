# v0.7.2 workspace UI/UX

Source: [Detailed UI/UX Improvement Specification & Design System Guide](https://docs.google.com/document/d/1ewfeSv9580SHLb1vN4OGqwX2NZ5fUmBFvsOmPNxMQeU/edit), read October 22, 2026. The normalized source text is retained in drive-ui-ux-v0.7.1.txt.

## Implemented experience

- Self-hosted Inter and JetBrains Mono, semantic slate/indigo/emerald/amber/rose styles, consistent controls/cards/status states and responsive layouts.
- Persistent collapsible navigation with six real Next.js routes: Overview, Inventory & findings, Cost allocation, Automation, Activity & delivery, Settings & integrations. Mobile navigation uses a modal. Workspace switching verifies the new credential before replacing context; credentials and resource data stay in React memory.
- Header command search, notifications from actual reliability state, snapshot selection, multi-scope filtering, profile/plan context and disconnect. Cmd/Ctrl-K, g d, g f, current-page Cmd/Ctrl-A, Shift-R and Escape support the related workflows.
- Actual observed trend counts with scoped-comparability gates, provider counts/drill-down and separate unknown/retail/net-savings metrics. No fabricated billing history or realized savings is shown.
- Virtualized TanStack inventory with search, provider/type/priority/tag filters and removable chips; sortable, reorderable, hideable/pinnable columns; 28/36/48px density; stable selection and pagination; selected CSV/JSON exports with CSV formula protection.
- Context-preserving 640px finding drawer with evidence, observed tags, actual cost basis, annualized retail estimate, server-returned code preview/copy/download and available scan delivery history. Bulk review lets users choose included findings. Viewer, quota, provider, plan and legacy-synthetic gates remain visible and enforced server-side.
- GitOps selection/preview/file inspection/acknowledged draft publishing, real durable PR history, Terraform plan upload preserving exact JSON for server duplicate-key validation, and the existing operational audit/replay flows.
- Allocation groups observed resources and priced subtotals by provider/scope. Settings shows real configuration and plan capabilities. Unsupported integrations and absent pricing/issue history are clearly stated.

## Verification boundaries

Playwright uses explicitly labeled interface QA fixtures and intercepts API calls. Screenshots are interface previews, not live customer/cloud evidence. Tests cover desktop/mobile navigation, filtering, density, selection, 10,000-row virtualization, drawer focus, role gates, command shortcuts, exact plan upload, explicit scan submission and GitOps acknowledgment. Automated axe checks are scoped to serious/critical WCAG violations in key views; manual assistive-technology and broad device testing remain necessary.

Illustrative instant savings, fabricated telemetry, deletion execution, fake SSO, customer-created integrations and Jira/ServiceNow assignment from the design guide are not exposed as working features. The backend's new durable Azure scan-job API is documented separately; this dashboard still uses the synchronous multi-cloud scan endpoint.
