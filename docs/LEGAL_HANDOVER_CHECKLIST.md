# Legal and privacy handover checklist

The customer-facing policy pages and consent prompts are published in this branch. Complete the checks below with the business owner before production handover. The repository identifies the brand as LashPro KE and the studio as Nairobi-based, but it does not contain verified legal-entity registration details or a street/postal address.

## Business identity and contact details
- [ ] Confirm the full registered legal name and any registered trading name that operates LashPro.
- [ ] Publish the business's physical studio address and postal/service address.
- [ ] Confirm the customer-care phone number and that support@lashpro.ke is monitored.
- [ ] Confirm the correct legal notice name for the data controller and add the verified address/contact details to the Privacy Policy and Terms.

## Data protection operations
- [ ] Determine and document whether LashPro must register as a data controller and/or processor with the Office of the Data Protection Commissioner (ODPC). Check the current registration rules and any applicable exemption; do not assume that small size automatically removes all obligations.
- [ ] Confirm which Fly.io, database, Cloudinary and email-service regions/processors are actually used in the live environment.
- [ ] Review provider contracts, access controls, breach response, backups, deletion and any cross-border transfer safeguards.
- [ ] Approve a retention schedule for customer accounts, order/transaction data, appointment records, support messages and security logs. Tax records generally have a five-year statutory retention period from the end of the reporting period, subject to exceptions and ongoing proceedings.
- [ ] Decide whether marketing messages will ever be sent. Do not repurpose order/booking contact details for marketing without the required separate lawful basis and opt-out process.
- [ ] Ensure staff have instructions for receiving and handling access, correction, objection, deletion and complaint requests.

## Consumer policy and operations
- [ ] Approve the voluntary seven-calendar-day change-of-mind return window and sealed/unused condition for products. This must not be applied to deny statutory remedies for defective, unsafe, incorrect or misdescribed goods.
- [ ] Confirm the existing 24-hour online appointment cancellation cutoff and publish a working customer-care route for requests inside that period.
- [ ] Confirm the process for issuing a durable order/booking confirmation and the applicable terms to customers after a remote agreement is accepted.
- [ ] Verify the on-site order and appointment flows, staff scripts and actual fulfilment practices match the published policies.

## Release checks
- [ ] Review these documents with Kenyan counsel or a qualified privacy/compliance adviser before live handover.
- [ ] Run the full CI test suite and inspect the deployed storefront and POS footer on mobile and desktop.
- [ ] Confirm the live storefront and POS hosts both serve /privacy/, /terms/ and /returns/.
