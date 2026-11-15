const ROLE_ORDER = [
  "president",
  "vice president",
  "secretary",
  "treasurer",
  "event coordinator",
  "industry partnership chair",
  "public relations chair",
  "community outreach chair",
  "technical director",
  "membership chair",
];

const MEMBER_ORDER = [
  "Lakshita Madhavan",
  "Stephanie Nicolaescu",
  "Anne Therese Argonza",
  "Sharanya Raj",
  "Saidarsha Karunakaran",
  "Garima Thapa",
  "Carlin Verano",
  "Manisha Palaniappan",
  "Caithy Liao",
  "Azka Faisal",
  "Priya Patel",
  "Meera James",
  "Diya Pottangadi",
];

const normalizeRole = (role) => String(role ?? "").trim().toLowerCase()
  .replace(/\bpartnerships\b/g, "partnership")
  .replace(/^pr chair$/, "public relations chair")
  .replace(/\s+/g, " ");
const roleRank = new Map(ROLE_ORDER.map((role, index) => [role, index]));
const memberRank = new Map(MEMBER_ORDER.map((name, index) => [name.toLowerCase(), index]));

export function orderProfiles(profiles) {
  return [...profiles].sort((a, b) => {
    const aName = (a.name ?? "").trim();
    const bName = (b.name ?? "").trim();
    const aRole = roleRank.get(normalizeRole(a.role)) ?? ROLE_ORDER.length;
    const bRole = roleRank.get(normalizeRole(b.role)) ?? ROLE_ORDER.length;
    const aMember = memberRank.get(aName.toLowerCase()) ?? MEMBER_ORDER.length;
    const bMember = memberRank.get(bName.toLowerCase()) ?? MEMBER_ORDER.length;
    return aRole - bRole || aMember - bMember || aName.localeCompare(bName);
  });
}
