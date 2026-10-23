## Card: writing requirements
One requirement per stable ID. Each states what it requires, in units, and how it will be checked:
```text
## R-3 Terminal voltage
Statement: v(k) = OCV(soc(k)) - i(k)*R0 - v1(k). Units: V, A, ohm. Discharge current is positive.
Acceptance: max |v - v_ref| <= 1e-6 V on the reference profiles (tests/voltageTest.m).
Provenance: brief section 2; R0 from datasheet table 3.
Open questions: none.
```
Before approval, check that the contract states, or explicitly leaves open:
- units and sign conventions for every input and output;
- sample time, time grid and interpolation rules (including what happens beyond table ends);
- the valid input domain, and for each invalid case either the exact error identifier or "unspecified";
- initial state, performance scale (for example 1e6 samples in under 4 s) and the MATLAB release and toolboxes;
- what is out of scope.

List every unknown as an open question. Do not invent a value. An item the contract does not state, or states unclearly, is a finding only when competing readings would change an approved outcome; otherwise it is a MINOR OPTIONAL IMPROVEMENT. A requirement nobody can test needs an acceptance method before approval.
