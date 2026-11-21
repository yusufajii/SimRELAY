// Event icons shared by the playback track and the sequence of events.
const S = (inner, title) => `<svg class="evi" viewBox="0 0 16 16" width="16" height="16" aria-label="${title}">${inner}</svg>`;

export const EV = {
  fault:   { pri: 10, label: "Fault inception", svg: S('<path d="M9.5 1 3.5 9h4L6 15l6.5-8.5h-4L10.5 1z" fill="#dc2626"/>', "Fault") },
  trip:    { pri: 9, label: "Relay trip", svg: S('<rect x="1.5" y="1.5" width="13" height="13" fill="#fee2e2" stroke="#dc2626" stroke-width="1.6"/><path d="M8.6 3.5 5.6 8.6h2.3L7 12.5l3.4-5.2H8.1z" fill="#dc2626"/>', "Trip") },
  cbopen:  { pri: 8, label: "Breaker open", svg: S('<path d="M1 8h3M12 8h3" stroke="#475569" stroke-width="1.5"/><rect x="4" y="4" width="8" height="8" fill="#fff" stroke="#16a34a" stroke-width="1.8"/>', "Breaker open") },
  dertrip: { pri: 7, label: "DER disconnected", svg: S('<circle cx="8" cy="8" r="6" fill="#fff" stroke="#64748b" stroke-width="1.5"/><path d="M4.6 8.4q1.7-2.6 3.4 0t3.4 0" fill="none" stroke="#64748b" stroke-width="1.2"/><path d="M3 13 13 3" stroke="#d97706" stroke-width="1.6"/>', "DER disconnected") },
  island:  { pri: 6, label: "Islanding", svg: S('<circle cx="8" cy="8" r="6" fill="none" stroke="#0f766e" stroke-width="1.6" stroke-dasharray="2.4 1.8"/><circle cx="8" cy="8" r="2" fill="#0f766e"/>', "Islanding") },
  cbclose: { pri: 5, label: "Breaker closed", svg: S('<path d="M1 8h3M12 8h3" stroke="#475569" stroke-width="1.5"/><rect x="4" y="4" width="8" height="8" fill="#dc2626" stroke="#991b1b" stroke-width="1.4"/>', "Breaker closed") },
  cleared: { pri: 4, label: "Fault cleared", svg: S('<circle cx="8" cy="8" r="6.3" fill="#fff" stroke="#15803d" stroke-width="1.5"/><path d="M5 8.2 7.2 10.4 11.2 5.8" fill="none" stroke="#15803d" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>', "Fault cleared") },
  pickup:  { pri: 3, label: "Relay pickup", svg: S('<circle cx="8" cy="8.6" r="5.6" fill="#fff" stroke="#7c3aed" stroke-width="1.5"/><path d="M8 5.6v3.2l2.2 1.4" fill="none" stroke="#7c3aed" stroke-width="1.4" stroke-linecap="round"/><path d="M6.4 1.6h3.2" stroke="#7c3aed" stroke-width="1.4"/>', "Pickup") },
  dir:     { pri: 2, label: "Direction decision", svg: S('<path d="M2 8h9" stroke="#7c3aed" stroke-width="1.7"/><path d="M14 8 9.5 4.6v6.8z" fill="#7c3aed"/>', "Direction") },
  dropout: { pri: 1, label: "Relay dropout", svg: S('<circle cx="8" cy="8.6" r="5.6" fill="#fff" stroke="#94a3b8" stroke-width="1.5"/><path d="M5.4 11.2 10.6 6" stroke="#94a3b8" stroke-width="1.4"/><path d="M6.4 1.6h3.2" stroke="#94a3b8" stroke-width="1.4"/>', "Dropout") },
};

// Map a relay or simulator event to an icon kind.
export function kindOf(e, source) {
  if (source === "relay") return ({ PICKUP: "pickup", DROPOUT: "dropout", TRIP: "trip", DTT: "trip", "52B": "cbopen", DIR: "dir" })[e.type] || "pickup";
  return ({ FAULT_ON: "fault", CB_OPEN: "cbopen", CB_CLOSE: "cbclose", DER_TRIP: "dertrip", ISLAND: "island", FAULT_CLEARED: "cleared" })[e.type] || "cleared";
}
