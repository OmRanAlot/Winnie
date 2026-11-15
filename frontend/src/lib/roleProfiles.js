const roleProfiles = {
  president: {
    summary: "Sets WiCS’s long-term direction, leads the Executive Board, and represents the organization across campus and the community.",
    responsibilities: [
      "Lead E-Board and General Body meetings, resolve internal issues, and guide board members toward shared goals.",
      "Coordinate with university leadership, faculty advisors, and the Computer Science department.",
      "Oversee planning for GirlHacks and the WiCS Gala, and lead future-board recruitment and transitions with the Vice President.",
      "Represent WiCS at university leadership events and community forums.",
    ],
  },
  "vice president": {
    summary: "Supports the President and strengthens internal operations, collaboration, and board continuity.",
    responsibilities: [
      "Act for the President when they are unavailable.",
      "Coordinate committees and check in with board members to support a productive, cohesive team.",
      "Lead future-board recruitment and transitions with the President.",
      "Coordinate end-of-semester reporting and goal-setting.",
    ],
  },
  secretary: {
    summary: "Keeps WiCS’s communications, records, and organizational information accurate, organized, and moving to the right people.",
    responsibilities: [
      "Manage Discord, meeting minutes, action items, deadlines, and attendance records.",
      "Send biweekly member newsletters and manage event listings and approvals on Highlander Hub.",
      "Maintain shared digital archives, calendars, and email; route inquiries and follow up on unanswered messages.",
    ],
  },
  treasurer: {
    summary: "Maintains WiCS’s financial health and ensures spending, funding, and reporting follow university policy.",
    responsibilities: [
      "Prepare annual and semester budgets, pursue funding, and attend Senate Cabinet meetings.",
      "Coordinate with Industry Partnerships on sponsorship funds and with Event Coordinators on purchases made at least three weeks ahead.",
      "Manage reimbursements and financial records, reconcile the club card with the President, and share monthly reports with the board.",
    ],
  },
  "event coordinator": {
    summary: "Plans and delivers WiCS events, handling registration, venues, supplies, schedules, and day-of logistics.",
    responsibilities: [
      "Hold weekly Events Committee meetings and plan engaging General Body meetings.",
      "Register events with OSIL, arrange parking and room bookings, and coordinate food, catering, and supplies.",
      "Track inventory, prepare materials in advance, manage event-day operations, and support GirlHacks and the WiCS Gala.",
    ],
  },
  "public relations chair": {
    summary: "Builds WiCS’s public presence through consistent visual design, storytelling, and community engagement.",
    responsibilities: [
      "Coordinate weekly PR Committee meetings and manage Instagram, Discord, LinkedIn, and other social channels.",
      "Create flyers, posters, merchandise, event campaigns, and visual themes for flagship events.",
      "Capture and share event recaps, and coordinate sponsor-facing materials and recognition with Industry Partnerships.",
    ],
  },
  "industry partnership chair": {
    summary: "Builds relationships with technology companies and recruiters, securing sponsorships and professional opportunities for WiCS members.",
    responsibilities: [
      "Maintain partner contacts and newsletters, and lead outreach for sponsorships and funding.",
      "Coordinate networking and recruiter workshops; pursue at least one company tour and two partner events each semester.",
      "Support GirlHacks communications and sponsorship materials, collaborate on sponsor recognition, and respond to partners within 72 hours.",
    ],
  },
  "community outreach chair": {
    summary: "Connects WiCS with campus organizations, faculty, alumni, and local professionals through outreach and mentorship.",
    responsibilities: [
      "Coordinate collaborations with campus clubs and offices and secure speakers for panels, workshops, and lectures.",
      "Maintain faculty and alumni relationships, organize one or two alumni events each semester, and coordinate mentorship chats.",
      "Lead campus tabling and recruit GirlHacks judges, volunteers, and mentors.",
    ],
  },
  "technical director": {
    summary: "The supplied position descriptions did not include a Technical Director overview or responsibilities.",
    responsibilities: [],
  },
  "membership chair": {
    summary: "The supplied position descriptions did not include a Membership Chair overview or responsibilities.",
    responsibilities: [],
  },
};

const normalize = (role) => String(role ?? "").trim().toLowerCase()
  .replace(/\bpartnerships\b/g, "partnership")
  .replace(/^pr chair$/, "public relations chair")
  .replace(/\s+/g, " ");

export function getRoleProfile(role) {
  return roleProfiles[normalize(role)] ?? null;
}
