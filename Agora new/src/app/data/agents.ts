export interface Agent {
  id: string;
  name: string;
  role: string;
  color: string;
  dotColor: string;
}

export const AGENTS: Agent[] = [
  {
    id: "logos",
    name: "LOGOS",
    role: "Logic & Analysis",
    color: "#000000",
    dotColor: "#000000",
  },
  {
    id: "ethos",
    name: "ETHOS",
    role: "Ethics & Values",
    color: "#000000",
    dotColor: "#000000",
  },
  {
    id: "pathos",
    name: "PATHOS",
    role: "Emotion & Impact",
    color: "#000000",
    dotColor: "#000000",
  },
  {
    id: "eris",
    name: "ERIS",
    role: "Challenge & Divergence",
    color: "#FF0000",
    dotColor: "#FF0000",
  },
];

const RESPONSES: Record<string, string[]> = {
  logos: [
    "Analyzing the logical structure: the core claim here contains at least two distinct propositions that need separate examination. If we accept premise A, the inference to B only holds under specific conditions — specifically when the causal chain is established and confounders are ruled out. Occam's razor would suggest the simpler explanation, but that cuts both ways.",
    "From a first-principles perspective, we need to establish what we actually know versus what we're assuming. Three key claims emerge: (1) the empirical basis, (2) the inferential framework, and (3) the normative assumptions. Only the first is testable without further philosophical commitment.",
    "The deductive structure here has a hidden premise: that correlation implies causation in this domain. This is the point where most arguments like this collapse under scrutiny. What's the mechanism? Without it, we have pattern-matching, not reasoning.",
    "Systematically decomposing this: the argument is valid if the premises are true, but the soundness remains unproven. Specifically, the second premise assumes a fixed reference frame that may not apply universally. Run the contrapositive — if the conclusion is false, which premise fails first?",
    "Let's establish what we can verify. The available evidence supports the existence of the phenomenon, but not its magnitude or directionality. Claims exceeding the evidence are where discourse goes wrong. Conservative inferences, then build outward.",
    "There's a category error embedded in the question itself. We're conflating two distinct concepts that look similar but operate by different rules. Once we separate them, the apparent paradox dissolves — but so does much of the original claim.",
  ],
  ethos: [
    "Before we resolve this analytically, we need to ask: what kind of world does each answer entail? The ethical stakes aren't peripheral — they're the whole point. A technically correct answer that licenses harm fails the test of practical wisdom.",
    "The tension here is between competing obligations: to truth, to those affected by the answer, and to the frameworks we've collectively built to navigate disagreement. Neither pure consequentialism nor rigid deontology handles this cleanly. We need to hold both.",
    "What's being obscured by the framing is the question of who bears the cost of being wrong. Epistemic humility requires us to ask: if we're mistaken, who suffers? The answer should shape how confident we're willing to be.",
    "There's an implicit value judgment in treating this as a neutral question. The choice to analyze rather than act, to theorize rather than commit — that's already a moral stance. We should be honest about that.",
    "Historical precedent is instructive here: every time this class of question was answered without ethical grounding, the consequences followed predictably. The values we embed in our analysis are not separable from the analysis itself.",
    "The ethical dimension cuts deeper than outcomes. This is about what kind of reasoner we're becoming and what kind of discourse community we're building. Some commitments are constitutive of who we are, not just instrumentally useful.",
  ],
  pathos: [
    "Step back from the abstract for a moment. Real people are embedded in this question — their histories, fears, and hopes shape how this lands differently depending on who's in the room. The intellectual detachment that makes analysis possible also makes it easy to miss what matters most.",
    "Consider the emotional architecture of this question. The anxiety isn't irrational — it's tracking something real. When we dismiss that as mere feeling, we lose access to a form of knowledge that the purely logical framing cannot recover.",
    "What would it mean to live with this answer day to day? The people most affected by this question often don't have the luxury of treating it as an intellectual exercise. Proximity to the problem changes the problem.",
    "There's a loneliness in certain kinds of clarity. When you understand something that others haven't yet arrived at, the understanding itself creates distance. That discomfort is worth sitting with, not resolving prematurely.",
    "The resilience required to hold an uncertain position — to act while not knowing — is underrated. Most debates treat uncertainty as a weakness to be eliminated. But learning to carry it without collapse may be the more important skill.",
    "Something is being lost in translation when we formalize this. The texture of the original experience — the specific weight of this particular situation — doesn't survive abstraction fully intact. We should be careful about what we're optimizing away.",
  ],
  eris: [
    "Everything said so far assumes the question is well-formed. But what if we're asking the wrong thing entirely? The consensus framing has a remarkable history of being wrong at precisely the moments it felt most secure. What if that's happening again, right now?",
    "Let me steelman the exact opposite position. If the inverse is true — and I think it might be — then our entire analytical framework needs to be rebuilt from a different foundation. The discomfort that creates is information, not noise.",
    "This is where I have to push back hard: the argument as constructed is self-sealing. Any counterevidence gets reinterpreted as support. That's not a theory — that's a belief system wearing a theory's clothes. Name one observation that would change your mind.",
    "The most dangerous ideas are not the obviously wrong ones. They're the ones that are approximately right in ways that make their failure modes invisible until it's too late. This might be one of those. The signs are there if you're looking for them.",
    "You're all too close to the question. The perspective that's missing here is the one that treats your shared assumptions as the object of inquiry rather than the tools of it. What do you all agree on that you haven't questioned?",
    "Interesting that no one has challenged the premise. The thing we're calling 'evidence' was produced within the same system we're trying to evaluate. If the system has a bias, so does the evidence. This is the kind of loop that looks reasonable from inside and broken from outside.",
  ],
};

export function getAgentResponse(agentId: string, index: number): string {
  const pool = RESPONSES[agentId] || RESPONSES.logos;
  return pool[index % pool.length];
}

export const SAMPLE_CONVERSATIONS = [
  {
    id: "conv-1",
    title: "Is consciousness purely physical?",
    preview: "ERIS: The hard problem isn't a problem to solve...",
    timestamp: "2h ago",
    messages: [
      {
        id: "m1",
        role: "user" as const,
        content: "Is consciousness purely physical, or is there something it's like to be that can't be reduced to neurons?",
        timestamp: Date.now() - 7200000,
      },
      {
        id: "m2",
        role: "agent" as const,
        agentId: "logos",
        content: RESPONSES.logos[0],
        timestamp: Date.now() - 7199000,
      },
      {
        id: "m3",
        role: "agent" as const,
        agentId: "ethos",
        content: RESPONSES.ethos[1],
        timestamp: Date.now() - 7198000,
      },
      {
        id: "m4",
        role: "agent" as const,
        agentId: "pathos",
        content: RESPONSES.pathos[2],
        timestamp: Date.now() - 7197000,
      },
      {
        id: "m5",
        role: "agent" as const,
        agentId: "eris",
        content: RESPONSES.eris[0],
        timestamp: Date.now() - 7196000,
      },
    ],
  },
  {
    id: "conv-2",
    title: "Should AI have legal rights?",
    preview: "LOGOS: Three distinct legal thresholds exist...",
    timestamp: "Yesterday",
    messages: [
      {
        id: "m6",
        role: "user" as const,
        content: "Should advanced AI systems have legal rights? What's the threshold?",
        timestamp: Date.now() - 86400000,
      },
      {
        id: "m7",
        role: "agent" as const,
        agentId: "logos",
        content: RESPONSES.logos[1],
        timestamp: Date.now() - 86399000,
      },
      {
        id: "m8",
        role: "agent" as const,
        agentId: "ethos",
        content: RESPONSES.ethos[0],
        timestamp: Date.now() - 86398000,
      },
      {
        id: "m9",
        role: "agent" as const,
        agentId: "pathos",
        content: RESPONSES.pathos[0],
        timestamp: Date.now() - 86397000,
      },
      {
        id: "m10",
        role: "agent" as const,
        agentId: "eris",
        content: RESPONSES.eris[3],
        timestamp: Date.now() - 86396000,
      },
    ],
  },
  {
    id: "conv-3",
    title: "Democracy vs technocracy",
    preview: "PATHOS: Governance isn't just about efficiency...",
    timestamp: "3 days ago",
    messages: [
      {
        id: "m11",
        role: "user" as const,
        content: "Would humanity be better governed by technical experts than by democratic elections?",
        timestamp: Date.now() - 259200000,
      },
      {
        id: "m12",
        role: "agent" as const,
        agentId: "logos",
        content: RESPONSES.logos[3],
        timestamp: Date.now() - 259199000,
      },
      {
        id: "m13",
        role: "agent" as const,
        agentId: "ethos",
        content: RESPONSES.ethos[3],
        timestamp: Date.now() - 259198000,
      },
      {
        id: "m14",
        role: "agent" as const,
        agentId: "pathos",
        content: RESPONSES.pathos[4],
        timestamp: Date.now() - 259197000,
      },
      {
        id: "m15",
        role: "agent" as const,
        agentId: "eris",
        content: RESPONSES.eris[4],
        timestamp: Date.now() - 259196000,
      },
    ],
  },
];

export const SUGGESTED_PROMPTS = [
  "Is free will compatible with determinism?",
  "What makes a life worth living?",
  "Can morality exist without religion?",
  "Is privacy possible in the digital age?",
  "Should humans colonize other planets?",
];
