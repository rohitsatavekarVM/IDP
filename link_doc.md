\# 11. Terrorism Premium Schedule (Certified Acts / TRIA)

\- name: terrorism\_premium\_schedule

&#x20; description: >

&#x20;   List of certified acts terrorism coverage parts and premiums from Schedule - Part I. For each entry, extract:

&#x20;   - coverage\_part: Name of coverage part (e.g. 'Property', 'General Liability', 'Total Certified Acts')

&#x20;   - premium: Amount charged (e.g. '$23.00', '$67.00', '$90.00')

&#x20; type: list\[dict]

&#x20; required: false

&#x20;

\- name: quoted\_schedule\_of\_coverages

&#x20; description: >

&#x20;   List of all coverage items from the quoted schedule of coverages across all sections(Property, Liability).

&#x20;   For each row, extract:

&#x20;   - category: The section header under which the item appears (e.g. Property, Liability)

&#x20;   - coverage\_name: Name of the coverage (e.g. Accounts receivable, Hired Auto Liability, Business Income - Dependent Properties)

&#x20;   - limit\_or\_option: Limit, duration, or option specified(e.g. '$25000 on and off premises', '12 months- Actual loss sustained')

&#x20;   - sub\_limit: Optional list of sub-line limits if present(e.g.\[{'item':'Inside Premise',limit:'$25000'},{'item':'Outside Premise','limit':'$25000'}])

&#x20;   - notes: Any conditional notes or exclusions

&#x20; type: list\[dict]

&#x20; required: false

