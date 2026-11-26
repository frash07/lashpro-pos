# Legal and privacy handover checklist

The customer-facing policy pages and consent prompts are published in this branch. The owner has identified LASHPRO BEAUTY VENTURES as the registered business name, Lashpro KE as the standard public brand, and “Girls Love Lashe” as the tagline. Complete the checks below before production handover. The studio postal/service address and phone numbers shown in policy pages still need confirmation.

## Business identity and contact details
- [x] Business identity supplied by the owner: LASHPRO BEAUTY VENTURES, trading as Lashpro KE; tagline: “Girls Love Lashe”. Confirm the exact legal spelling against the registration record during handover.
- [ ] Publish the business's physical studio address and postal/service address.
- [ ] Confirm the customer-care phone number and that support@lashpro.ke is monitored.
- [x] Add the supplied registered business name and Lashpro KE trading brand to the Privacy Policy.
- [ ] Confirm the correct legal notice name for the data controller and add the verified postal address/contact details to the Privacy Policy and Terms.

## Data protection operations
- [ ] The business owner states the business is exempt from ODPC registration. Confirm and retain the basis for that exemption with a qualified Kenyan privacy adviser. The [ODPC FAQ](https://www.odpc.go.ke/faqs/) describes a small-controller exemption subject to both turnover and staffing thresholds and categories that must register regardless; the Lashpro academy/training activity may need specific review.
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
