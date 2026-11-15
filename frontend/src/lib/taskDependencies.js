const ROLE = {
  president: /\bpresident\b/i,
  vicePresident: /\bvice president\b/i,
  secretary: /\bsecretary\b/i,
  treasurer: /\btreasurer\b/i,
  eventCoordinator: /\bevent coordinator\b/i,
  publicRelations: /\b(public relations|pr chair)\b/i,
  industryPartnerships: /\bindustry partnership\b/i,
  technicalDirector: /\btechnical director\b/i,
};

const PROJECT_ANCHORS = [
  /\bgirlhacks?\b/i,
  /\bwics gala\b|\bgala\b/i,
  /\bgbm\b|\bgeneral body meeting\b/i,
  /\bcareer panel\b|\bcareer fair\b/i,
  /\bhackathon\b/i,
  /\bcompany tour\b/i,
  /\bworkshop\b/i,
];

const normalize = (value) => String(value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const contentOf = (task) => normalize([
  task.title, task.description, task.notes, task.event, task.project_name, task.event_tag,
].filter(Boolean).join(" "));

function assignedRoles(task, peopleById) {
  const memberIds = new Set([task.assignee, ...(task.assignees ?? [])].filter(Boolean));
  const roles = [...memberIds].map((id) => peopleById.get(id)?.role).filter(Boolean);
  return roles.length ? roles.join(" ") : String(task.role ?? task.seat ?? "");
}

function roleMatches(task, peopleById, patterns) {
  const roles = assignedRoles(task, peopleById);
  return !roles || patterns.some((pattern) => pattern.test(roles));
}

function projectLabel(task) {
  const label = normalize(task.event || task.project_name || task.event_tag);
  return label && label !== "miscellaneous" ? label : "";
}

function sameProject(left, right) {
  const leftLabel = projectLabel(left);
  const rightLabel = projectLabel(right);
  if (leftLabel && rightLabel) return leftLabel === rightLabel;
  const leftText = contentOf(left);
  const rightText = contentOf(right);
  return PROJECT_ANCHORS.some((anchor) => anchor.test(leftText) && anchor.test(rightText));
}

function createsCycle(graph, taskId, dependsOnId) {
  const pending = [dependsOnId];
  const visited = new Set();
  while (pending.length) {
    const current = pending.pop();
    if (current === taskId) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    pending.push(...(graph.get(current) ?? []));
  }
  return false;
}

function hasCandidateContext(text) {
  return /\b(candidate|applicant|interview|recruitment|election|e board|executive board|officer)\b/.test(text);
}

function isShortlisting(task) {
  const text = contentOf(task);
  return /\bshortlist(?:ing)?\b/.test(text)
    || (/\b(interview|screen(?:ing)?)\b/.test(text) && /\b(candidate|applicant)s?\b/.test(text));
}

function isDeliberation(task) {
  const text = contentOf(task);
  return /\b(deliberat(?:e|ion|ing)?|discuss|review|evaluate)\b/.test(text)
    && !/\b(announce|notify|publish|communicate)\b/.test(text)
    && (hasCandidateContext(text) || /\be board\b|\bexecutive board\b/.test(text));
}

function isDecisionAnnouncement(task) {
  const text = contentOf(task);
  return /\b(announc(?:e|ing|ement)|notify|publish|communicate|share)\b/.test(text)
    && /\b(candidate|applicant|decision|selection|e board|executive board|officer|election)\b/.test(text);
}

function isSupplyList(task) {
  const text = contentOf(task);
  return /\b(list|inventory)\b/.test(text)
    && /\b(suppl(?:y|ies)|materials?|food|catering)\b/.test(text);
}

function isSupplyPurchase(task) {
  const text = contentOf(task);
  return /\b(purchas(?:e|ing)|order(?:ing)?|buy|procur(?:e|ing))\b/.test(text)
    && /\b(suppl(?:y|ies)|materials?|food|catering)\b/.test(text);
}

function isVenueOrRegistration(task) {
  return /\b(room booking|book(?:ing)? (?:a )?(?:room|space)|reserve(?:d|s|ing)? (?:a )?(?:room|space)|campus space|event registration|register(?:ed|ing)? (?:an )?event)\b/.test(contentOf(task));
}

function isOfficialEventPosting(task) {
  return /\b(highlander hub|event posting|post(?:ing)? (?:the )?event|event approval)\b/.test(contentOf(task));
}

function isSponsorOutreach(task) {
  const text = contentOf(task);
  return /\b(prospectus|outreach|secure|recruit)\b/.test(text)
    && /\b(sponsor|sponsorship|corporate partner|company partner)\b/.test(text);
}

function isSponsorFunding(task) {
  const text = contentOf(task);
  return /\b(invoice|incoming funds|track|reconcile|process)\b/.test(text)
    && /\b(sponsor|sponsorship|partner funds)\b/.test(text);
}

function isSponsorPromotion(task) {
  const text = contentOf(task);
  return /\b(logo|highlight|promot|social media|marketing)\b/.test(text)
    && /\b(sponsor|sponsorship|partner)\b/.test(text);
}

function isGirlHacksRecruitment(task) {
  const text = contentOf(task);
  return /\b(recruit|recruitment|secure)\b/.test(text)
    && /\b(judges?|volunteers?|mentors?)\b/.test(text)
    && /\bgirlhacks?\b/.test(text);
}

function isDayOfLogistics(task) {
  const text = contentOf(task);
  return /\b(day of|day-of|event execution|manage event logistics|run the event)\b/.test(text);
}

function isEventRecap(task) {
  const text = contentOf(task);
  return /\b(recap|post-event|post event|event photos|capture photos|record content)\b/.test(text);
}

function explicitlyFollows(task, prerequisite) {
  const taskText = contentOf(task);
  const prerequisiteTitle = normalize(prerequisite.title);
  if (prerequisiteTitle.length < 5) return false;
  const titleIndex = taskText.indexOf(prerequisiteTitle);
  if (titleIndex < 0) return false;
  return /\b(after|once|following|depends on|requires?|waiting on|blocked by)\b/.test(
    taskText.slice(Math.max(0, titleIndex - 80), titleIndex),
  );
}

function addCandidate(candidates, graph, task, prerequisite, reason) {
  if (!task?.id || !prerequisite?.id || task.id === prerequisite.id) return;
  if (graph.get(task.id)?.has(prerequisite.id) || createsCycle(graph, task.id, prerequisite.id)) return;
  graph.get(task.id)?.add(prerequisite.id);
  candidates.push({ task_id: task.id, depends_on_id: prerequisite.id, reason });
}

export function inferTaskDependencies(tasks, people = []) {
  const peopleById = new Map(people.map((member) => [member.id, member]));
  const graph = new Map(tasks.map((task) => [
    task.id,
    new Set(task.dependsOn || (task.dep ? [task.dep] : [])),
  ]));
  const candidates = [];

  for (const task of tasks) {
    for (const prerequisite of tasks) {
      if (explicitlyFollows(task, prerequisite)) {
        addCandidate(candidates, graph, task, prerequisite,
          "The task description explicitly says it follows this prerequisite.");
      }
    }
  }

  const shortlists = tasks.filter(isShortlisting);
  const deliberations = tasks.filter((task) => isDeliberation(task)
    && roleMatches(task, peopleById, [ROLE.president, ROLE.vicePresident]));
  const announcements = tasks.filter((task) => isDecisionAnnouncement(task)
    && roleMatches(task, peopleById, [
      ROLE.president, ROLE.vicePresident, ROLE.secretary,
    ]));
  for (const deliberation of deliberations) {
    for (const shortlist of shortlists) {
      if (hasCandidateContext(contentOf(shortlist))) {
        addCandidate(candidates, graph, deliberation, shortlist,
          "Board deliberation follows the shortlist of interview candidates.");
      }
    }
  }
  for (const announcement of announcements) {
    for (const deliberation of deliberations) {
      addCandidate(candidates, graph, announcement, deliberation,
        "Candidate decisions should be announced after E-Board deliberation.");
    }
  }

  const supplyLists = tasks.filter((task) => isSupplyList(task)
    && roleMatches(task, peopleById, [ROLE.eventCoordinator]));
  const purchases = tasks.filter((task) => isSupplyPurchase(task)
    && roleMatches(task, peopleById, [ROLE.treasurer]));
  for (const purchase of purchases) {
    for (const list of supplyLists) {
      if (sameProject(purchase, list)) {
        addCandidate(candidates, graph, purchase, list,
          "The Treasurer's event purchase depends on the Event Coordinator's supply list.");
      }
    }
  }

  const venueTasks = tasks.filter((task) => isVenueOrRegistration(task)
    && roleMatches(task, peopleById, [ROLE.eventCoordinator]));
  const postingTasks = tasks.filter((task) => isOfficialEventPosting(task)
    && roleMatches(task, peopleById, [ROLE.secretary]));
  for (const posting of postingTasks) {
    for (const venue of venueTasks) {
      if (sameProject(posting, venue)) {
        addCandidate(candidates, graph, posting, venue,
          "Official event posting follows confirmed event registration or room booking.");
      }
    }
  }

  const sponsorOutreach = tasks.filter((task) => isSponsorOutreach(task)
    && roleMatches(task, peopleById, [ROLE.industryPartnerships]));
  const sponsorFunding = tasks.filter((task) => isSponsorFunding(task)
    && roleMatches(task, peopleById, [ROLE.treasurer]));
  const sponsorPromotion = tasks.filter((task) => isSponsorPromotion(task)
    && roleMatches(task, peopleById, [ROLE.publicRelations, ROLE.technicalDirector]));
  for (const followup of [...sponsorFunding, ...sponsorPromotion]) {
    for (const outreach of sponsorOutreach) {
      if (sameProject(followup, outreach)) {
        addCandidate(candidates, graph, followup, outreach,
          "Sponsor follow-up depends on partner outreach and sponsorship confirmation.");
      }
    }
  }

  const girlHacksRecruitment = tasks.filter(isGirlHacksRecruitment);
  const dayOfTasks = tasks.filter((task) => isDayOfLogistics(task)
    && roleMatches(task, peopleById, [ROLE.eventCoordinator]));
  for (const dayOf of dayOfTasks) {
    for (const recruitment of girlHacksRecruitment) {
      if (sameProject(dayOf, recruitment)) {
        addCandidate(candidates, graph, dayOf, recruitment,
          "GirlHacks event logistics depend on recruiting judges, volunteers, and mentors.");
      }
    }
  }

  const recapTasks = tasks.filter((task) => isEventRecap(task)
    && roleMatches(task, peopleById, [ROLE.publicRelations]));
  for (const recap of recapTasks) {
    for (const execution of dayOfTasks) {
      if (sameProject(recap, execution)) {
        addCandidate(candidates, graph, recap, execution,
          "The event recap follows the event's day-of logistics and execution.");
      }
    }
  }

  return candidates;
}
