# Mid-Review Video Script

Total target: 20 to 22 minutes. Four speakers, seven slides each, about five minutes per speaker.

These are speaking notes, not a word-for-word reading. Every fact below is already on the slide, so look at the panel, not the screen. The one thing worth memorising is the boundary sentence: computer vision decides, the language model explains.

---

## Speaker 1: Nithin H

Slides 1 to 7. Target five minutes, roughly 42 seconds per slide.

Goal: Establish the problem and the pipeline, and set the boundary between vision and language that the other three speakers rely on.

### Slide 1 - Title and boundary

- Give the project title, then the team and who speaks when.
- State the boundary immediately: computer vision decides, the language model explains. This is the sentence the whole presentation defends.
- Say that the mid-review focuses on the vision side because that is where the safety decision is actually made.

### Slide 2 - How the presentation is organised

- Walk the table quickly so the evaluators know all four of us speak for a similar length of time.
- Point out that the survey is not a reading list: speakers two and three each close with a synthesis slide that states what the papers left unsolved.

### Slide 3 - CCTV is already everywhere, but review is reactive

- Start from the fact that cameras are already installed; the missing piece is not hardware, it is interpretation.
- Contrast the two columns directly. Read one weakness of a bare alert, then the matching need on the right. Do this for two or three pairs, not all four.
- Land on the idea that a safety officer needs a record, not a notification.

### Slide 4 - Problem statement

- Read the precise statement once, slowly. It is the graded deliverable.
- Then use the four blocks to show the statement decomposes cleanly: what must be perceived, what must be reasoned about, what must be produced.
- Spend real time on the out-of-scope block. Saying what we are not doing is what makes the scope credible.

### Slide 5 - Vision decides, language explains

- This is the most important conceptual slide. Do not rush it.
- Explain that if one model both detected and explained, there would be no independent record to audit its story against.
- Explain the weak-evidence path: unknown PPE state leads to an inconclusive incident, and the rule still decides, not the model.

### Slide 6 - Proposed computer vision pipeline

- Trace the diagram left to right, naming the question each stage answers: what is in the frame, who is it, what are they wearing, is that a violation.
- Stress that nothing downstream can override an earlier stage.
- Note that the language model sits entirely to the right of this diagram.

### Slide 7 - The structured incident record

- Read three or four rows, not all eight. Pick worker, time, evidence and status.
- Emphasise the status row: confirmed versus inconclusive, and that it is never silently upgraded.
- Close by saying that every later mention of an incident means this object, and hand over to speaker two.

---

## Speaker 2: Pavan Kumar K N

Slides 8 to 14. Target five minutes, roughly 42 seconds per slide.

Goal: Cover the six PPE and object-detection papers, then state what detection alone cannot deliver.

### Slide 8 - Nath et al. 2020

- Title on screen: Deep learning for site safety: real-time detection of protective equipment. Area: PPE detection.
- What they did: YOLO-based detector trained on a crowdsourced construction image dataset. Compares three strategies: detect PPE items directly, detect combined worker-plus-PPE classes, or detect the worker then classify the crop. The combined-class approach reached the best mean average precision of 72.3 percent. The third strategy pairs a worker detector with a separate CNN classifier per crop.
- Why it matters: Demonstrates PPE compliance checking on genuine site imagery, not staged photos. Shows classifying a cropped worker beats detecting small PPE items directly. Publishes construction-specific labels instead of reusing generic object classes. Establishes the accuracy range a student-scale PPE system can realistically hit.
- Where it stops: Output is a per-frame compliance label with no worker identity or duration. Covers helmet and vest only, with no reasoning about occlusion or camera angle. A fixed-label classifier must still pick a class when the helmet is not visible.
- How it shapes our design: Validates our detect-then-classify design: YOLO finds the worker, a second head reads PPE from the crop. We keep their crop-classifier idea but add an explicit unknown state for poor visibility. Their reported accuracy gives us a realistic target for our own detection metric.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 9 - Wu et al. 2019

- Title on screen: Automatic detection of hardhats worn by construction personnel. Area: Hardhat detection.
- What they did: Single-shot detector with an attention mechanism aimed at small objects. Introduces a benchmark of site images labelled by hardhat colour. Detects five classes: no-hardhat plus blue, white, yellow and red hardhats. Uses a lightweight backbone chosen for practical on-site deployment.
- Why it matters: Confirms helmet status is readable from CCTV-resolution imagery. Colour classes let a system separate roles such as visitor, worker and supervisor. Shows attention on shallow layers measurably improves small-object recall. Provides a reusable public benchmark for hardhat detection.
- Where it stops: Helmet only, so a worker missing a vest or standing in a restricted zone is invisible. Per-image detection with no tracking, so one violation recounts on every frame. Produces a box on a frame rather than a record of what happened.
- How it shapes our design: Supports rule R1 on mandatory helmets and flags small-object recall as a real risk. Shows why our scope must cover vest and zone rules, not hardhats alone. Their colour classes are a candidate later extension for role-aware rules.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 10 - Fang et al. 2018

- Title on screen: Computer vision applications in construction safety assurance. Area: Survey.
- What they did: Reviews computer vision work across detection, tracking and behaviour analysis. Groups applications by hazard: falls, PPE non-compliance, equipment proximity, unsafe acts. Compares handcrafted-feature methods against early deep learning approaches. Catalogues the datasets and evaluation practices in use across the field.
- Why it matters: Establishes vision-based safety assurance as a legitimate, active research area. Identifies that most systems stop at detection and never close the loop to action. Highlights the absence of shared construction-specific benchmarks. Gives a shared vocabulary for hazard types that we adopt for our rules.
- Where it stops: Surveyed systems emit alerts, not records a safety officer can review and act on. Almost no attention to uncertainty, occlusion, or explaining a decision. Little work links a detected hazard to a regulation or a required response.
- How it shapes our design: This survey defines our central gap: move from a raw alert to a usable incident. Its hazard taxonomy maps almost directly onto our rules R1 to R5. Its note on missing explanations is what justifies our LLM briefing layer.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 11 - Redmon and Farhadi 2018

- Title on screen: YOLOv3: An Incremental Improvement. Area: Object detection.
- What they did: Single-stage detector predicting boxes, objectness and classes in one forward pass. Darknet-53 backbone predicting at three scales to cover different object sizes. Independent per-class logistic classifiers instead of a softmax over classes. Trained at several input resolutions to trade speed against accuracy.
- Why it matters: Made real-time detection practical on a single GPU at usable accuracy. Three-scale prediction substantially improved small-object detection. Became the baseline that the construction-safety papers above are built on. Its architecture is still the reference point every later tracker assumes.
- Where it stops: A general-purpose detector with no notion of who a person is between frames. No temporal reasoning, so it cannot express duration or persistence. Trained on generic classes; helmets and vests are not in its vocabulary.
- How it shapes our design: Justifies a single-stage YOLO detector as the first stage of our pipeline. Its multi-scale design matters because workers are small in wide CCTV views. Shows we must fine-tune on construction data rather than use pretrained weights.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 12 - Bochkovskiy et al. 2020

- Title on screen: YOLOv4: Optimal Speed and Accuracy of Object Detection. Area: Object detection.
- What they did: CSPDarknet backbone with a path-aggregation neck and spatial pyramid pooling. Training additions such as mosaic augmentation and an IoU-aware box loss. Explicitly optimised for one conventional GPU rather than a training cluster. Ablates which training tricks improve accuracy at no inference cost.
- Why it matters: Reaches 43.5 average precision at 65 frames per second on a single GPU. Shows large accuracy gains come from training strategy, not just architecture. Puts strong detection within reach of modest, student-scale hardware. Its ablations tell us which training choices are worth our limited time.
- Where it stops: Still returns only boxes and class labels for the current frame. No identity, no duration and no safety verdict of any kind. Accuracy on partly hidden construction objects such as a tilted helmet is untested.
- How it shapes our design: Confirms our hardware budget is realistic for offline processing of recorded clips. Its augmentation recipe is directly reusable when we fine-tune on site footage. Reinforces that detection quality is mostly a training-data problem.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 13 - Wang et al. 2024

- Title on screen: YOLOv9: Learning What You Want to Learn. Area: Object detection.
- What they did: Programmable gradient information addresses signal loss through deep layers. GELAN architecture combines gradient-path planning with efficient aggregation. Auxiliary reversible branches are used in training and dropped at inference. Compared against the whole YOLO lineage under matched parameter budgets.
- Why it matters: Better accuracy than earlier YOLO versions with fewer parameters and less compute. Shows the information bottleneck, not model size, was limiting deep detectors. Provides a current, actively maintained reference implementation. Confirms the YOLO family is still improving, so the choice is not dated.
- Where it stops: A benchmark-driven paper with no construction or safety evaluation. Says nothing about tracking, rules or incident reporting. Gains are reported on a benchmark that contains no PPE classes.
- How it shapes our design: Justifies choosing a recent YOLO-family model as our detection backbone. Its parameter efficiency helps us stay inside a free-tier cloud demo budget. We will still validate on our own site frames rather than trust benchmark numbers.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 14 - Synthesis: detection gives boxes, not incidents

- Do not re-summarise each paper. State the two columns as a pair of claims.
- Left column: these six papers prove PPE is detectable and that detect-then-classify is the right shape.
- Right column: every one of them stops at a per-frame label, with no identity, no duration, no uncertainty and no rule.
- Read the bottom block as the bridge into speaker three's tracking papers.

---

## Speaker 3: Pranav Nayak

Slides 15 to 21. Target five minutes, roughly 42 seconds per slide.

Goal: Cover the six tracking, harness and activity-recognition papers, then show why rules need time, identity and context.

### Slide 15 - Zhang et al. 2022

- Title on screen: ByteTrack: Multi-Object Tracking by Associating Every Detection Box. Area: Tracking.
- What they did: Associates every detection box with tracks in two stages, including weak ones. High-confidence boxes match first using Kalman motion prediction and box overlap. Remaining low-confidence boxes then match unmatched tracks to recover occlusions. Deliberately uses no appearance embedding, which keeps the tracker cheap.
- Why it matters: Reaches 80.3 MOTA and 77.3 IDF1 on MOT17 at around 30 frames per second. Shows most tracking failures come from discarding low-confidence detections. Simple enough to implement, debug and explain inside a semester project. Needs no extra model to train, which keeps our pipeline auditable.
- Where it stops: Assumes a reasonably stable camera and can still switch identities in dense crowds. Without appearance features it cannot re-identify a worker who leaves and returns. Tracking quality is capped by detector quality on the same frames.
- How it shapes our design: Our primary tracker, giving each worker an identity that persists across the clip. Turns a bare alert into worker 17 was uncovered for 4.3 seconds. Its weak-box recovery is exactly what we need when workers pass behind scaffolding.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 16 - Aharon et al. 2022

- Title on screen: BoT-SORT: Robust Associations Multi-Pedestrian Tracking. Area: Tracking.
- What they did: Combines Kalman motion prediction with appearance re-identification embeddings. Adds camera-motion compensation estimated by registering consecutive frames. Improves the Kalman state using box width and height rather than aspect ratio. Fuses overlap and appearance distance into a single association cost.
- Why it matters: Ahead of motion-only trackers on identity metrics on the same MOT17 benchmark. Camera-motion compensation directly addresses shaky or panning site cameras. Shows appearance features recover identities that motion alone loses. Its width-and-height state estimate is a cheap improvement we can adopt alone.
- Where it stops: Higher compute plus an extra re-identification model to train and maintain. Appearance embeddings are weak when every worker wears an identical uniform. More hyperparameters to tune, which is a real cost on a short timeline.
- How it shapes our design: Our documented fallback if ByteTrack produces too many identity switches. Relevant if our source footage is handheld rather than from a fixed mount. Its identical-uniform weakness is a limitation we will state in evaluation.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 17 - Wojke et al. 2017

- Title on screen: Simple Online and Realtime Tracking with a Deep Association Metric. Area: Tracking.
- What they did: Extends SORT with a deep appearance descriptor trained for person re-identification. A matching cascade prioritises recently seen tracks to reduce fragmentation. Combines a motion distance with a cosine appearance distance. Runs the appearance network on every detection crop in every frame.
- Why it matters: Cut identity switches by roughly 45 percent compared with plain SORT. Established the appearance-plus-motion template that later trackers refined. Still the most widely reproduced tracking baseline, so it is a fair comparison. Its matching cascade is a well-documented idea we can borrow if needed.
- Where it stops: Older, and outperformed by ByteTrack and BoT-SORT on crowded sequences. The appearance network adds a forward pass per detection, slowing throughput. Assumes detections are reliable and discards low-confidence boxes entirely.
- How it shapes our design: The baseline we cite to explain why identity tracking is needed at all. Its discarding of weak detections is the precise failure ByteTrack fixes. Useful as a sanity comparison if our ByteTrack numbers look implausible.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 18 - Fang et al. 2018b

- Title on screen: Falls from heights: computer vision based safety harness detection. Area: Construction safety.
- What they did: Two-stage pipeline: a detector locates workers, a second network checks for a harness. Targets workers operating at height, where fall protection is mandatory. Trained on site images of scaffolding and structural steel work. Reports precision and recall for harness presence, not only detection accuracy.
- Why it matters: Shows vision can target the highest-consequence hazard class, falls from height. Validates a detect-then-verify pattern for a specific safety attribute. Demonstrates a context-dependent rule: the harness only matters when at height. Reports attribute-level precision and recall, which is how we will score PPE.
- Where it stops: Judges each frame independently, with no duration or persistence requirement. Harness straps are thin and frequently occluded, which limits reliability. Does not determine elevation automatically from the scene.
- How it shapes our design: Directly supports rule R5 on elevated edges and fall risk. Confirms our two-stage detect-then-classify structure for PPE attributes. Its context dependence is why our rules combine PPE state with zone information.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 19 - Sanhudo et al. 2021

- Title on screen: Activity classification of construction workers. Area: Activity recognition.
- What they did: Classifies worker activity from wearable accelerometer signals. Compares several classifiers over features extracted from signal windows. Focuses on labour-intensive tasks relevant to ergonomic and safety risk. Uses time-windowed features rather than instantaneous readings.
- Why it matters: Shows worker behaviour is machine-recognisable into meaningful categories. Time-windowed classification is markedly more reliable than per-instant labels. Links activity recognition to safety outcomes, not only productivity. Confirms activity categories are stable enough to be worth detecting at all.
- Where it stops: Sensor-based, so every worker must wear and maintain a device. Produces no visual evidence, so a supervisor cannot verify the classification. Does not scale to a site that already has cameras but no wearables.
- How it shapes our design: Reinforces our choice of time windows over per-frame labels in the rule engine. Its lack of visual evidence is why our incident cards must carry an image crop. Motivates deriving activity context from video rather than from extra hardware.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 20 - Luo et al. 2018

- Title on screen: Recognising diverse construction activities in site images. Area: Activity recognition.
- What they did: A relevance network relates detected objects to candidate activity classes. Handles many activity classes in cluttered, unconstrained site photographs. Uses object co-occurrence as evidence rather than whole-image features. Evaluated across a wide range of real construction activity categories.
- Why it matters: Demonstrates activity recognition works on genuinely messy site imagery. Object-relation reasoning generalises better than whole-image classification. Establishes that context, not just the worker, decides whether a scene is unsafe. Shows a model can use the scene, not just the person, as safety evidence.
- Where it stops: Per-image classification with no tracking, so it cannot measure how long anything lasted. Cannot separate a worker passing through a zone from one working inside it. No mechanism to express uncertainty when the scene is ambiguous.
- How it shapes our design: Its per-frame limitation is the clearest argument for our track-first design. Its object-relation idea informs how we compute worker-to-zone relations. Confirms that a single frame cannot support a defensible safety verdict.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 21 - Synthesis: rules need time, identity and context

- Same structure as slide fourteen: what tracking gives us, what the activity papers warn us about.
- The key line is that duration is what separates a real breach from a worker walking through a zone.
- Use the bottom block to introduce debouncing, then hand over to speaker four.

---

## Speaker 4: Desu Sree Vardhan

Slides 22 to 28. Target five minutes, roughly 42 seconds per slide.

Goal: Cover the three multimodal papers, map the research gaps to design decisions, and close on evaluation, scope and next steps.

### Slide 22 - Achiam et al. 2023

- Title on screen: GPT-4 Technical Report. Area: Multimodal LLM.
- What they did: Transformer model accepting interleaved image and text input and producing text. Post-trained with reinforcement learning from human feedback for instruction following. Evaluated on academic and professional exams alongside standard benchmarks. Reports a dedicated safety and refusal evaluation beside the capability numbers.
- Why it matters: Shows one model can describe and reason about image content in plain language. Strong instruction following makes format-controlled output practical. Its documented refusal behaviour is a usable building block for a safety product. Sets the expectation that a visual explanation can read as genuinely useful.
- Where it stops: Closed weights behind an external API, so evidence crops leave our infrastructure. Still invents confident detail that is not present in the image. Gives no calibrated confidence, so its judgement cannot serve as a verdict.
- How it shapes our design: Supports calling a vision model only to adjudicate cases our pipeline marks unknown. Its hallucination risk is why the LLM never overrides a rule outcome in our design. Its refusal work backs our guardrail that declines legal-verdict questions.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 23 - Liu et al. 2023

- Title on screen: Visual Instruction Tuning (LLaVA). Area: Vision-language model.
- What they did: Connects a frozen vision encoder to a language model through a projection layer. Trained on machine-generated multimodal instruction-following data. Two stages: align the projection first, then instruction-tune end to end. Evaluated on visual question answering and open-ended visual conversation.
- Why it matters: Open-weight proof that visual question answering can run on self-hosted hardware. Shows synthetic instruction data is enough to teach visual conversation cheaply. Gives a reproducible reference architecture we could realistically deploy. Removes any dependency on a paid API for the explanation layer.
- Where it stops: Not construction-specific and untested on low-resolution CCTV crops. Weaker than closed models on fine detail such as a partly hidden strap. Ungrounded by default; it answers even with no supporting visual evidence.
- How it shapes our design: Our open-weight option if evidence crops cannot be sent to an external API. Its grounding weakness motivates an overlap check between answer and evidence. Baseline for the idea of explaining an evidence crop in plain language.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 24 - Yang et al. 2024

- Title on screen: Qwen2.5 Technical Report. Area: Open-weight LLM.
- What they did: Open-weight language model family spanning roughly 0.5 to 72 billion parameters. Large-scale pretraining followed by a long post-training stage for instructions. Small variants explicitly targeted at resource-constrained deployment. Reports structured-output and instruction-adherence benchmarks, not only knowledge.
- Why it matters: A 1.5 billion parameter model small enough to fine-tune with LoRA on one GPU. Open weights let the narration layer run entirely inside our own deployment. Reliable structured output makes template-constrained narration feasible. Small enough that the whole narration layer stays inside our own deployment.
- Where it stops: Text-only at the size we can afford, so it cannot look at an evidence crop. Small models invent detail more readily than their larger siblings. Cannot replace any part of the computer vision pipeline.
- How it shapes our design: Base model for our LoRA narration experiment over incident cards. Receives only the structured card fields as text, never the raw image. Its invention risk is why narration is template-constrained and evidence-checked.
- Delivery: read the method column briefly, then spend your time on the limitation and the how-we-use-it column. That link is what is being graded.

### Slide 25 - Research gaps mapped to design decisions

- This is the payoff slide for the whole survey. Go row by row.
- For each row, name the paper where we saw the gap, then the concrete design decision it forced. The pairing is what earns the literature-survey marks.
- Close with the note at the bottom: fifteen papers, each one either a component we reuse or a limitation we designed around.

### Slide 26 - Evaluation plan

- Be explicit that we are claiming no results yet, only a measurement plan.
- Explain why each metric was chosen, especially the unknown rate on the PPE head: a high unknown rate is acceptable, a confident wrong call is not.
- Mention that usability is measured on a first-time reviewer, not on ourselves.

### Slide 27 - Scope and team split

- Read the team table quickly; the detail is on the slide.
- Spend the time on the two scope blocks. Out-of-scope items show we understand what a semester can actually deliver.

### Slide 28 - Where we are and what comes next

- Read the one-sentence summary as written; it closes the loop with slide one.
- Name the three mid-review deliverables: title, survey, problem statement.
- Finish with what will be demonstrated at the final review, then thank the panel.

---

## Handover lines

- Speaker 1 to 2: that is the pipeline and the record it produces. Pavan will now show which parts of it the literature already solves.
- Speaker 2 to 3: detection gives us boxes. Pranav will explain why boxes on their own can never become an incident.
- Speaker 3 to 4: with identity and duration in place, Sree Vardhan will cover explanation, the research gaps, and how we plan to measure all of it.
- Speaker 4 close: thank the panel and offer to take questions.

## If you are running long

- On a paper slide, drop the method column to one sentence. Never drop the limitation or the how-we-use-it column.
- On slide 7, read three rows instead of eight.
- On slide 26, name the six components and one metric, and skip the reasoning.
