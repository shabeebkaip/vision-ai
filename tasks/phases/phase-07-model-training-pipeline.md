## Phase 7 — Model training pipeline (weeks 8 to 20)

About 21 developer-days (CV, with DO and BE help), plus labelling time. This is how we teach the system objects the standard model does not know: helmets, vests, hairnets, forklifts, mops, shelf gaps. The loop is: collect frames → pre-label automatically → people correct → train on a rented GPU → test on the video library → release to boxes in stages → learn from managers' "False alarm" taps → repeat monthly.

**Model release channels:** `dev` (developer laptops) → `staging` (office box) → `canary` (one customer site) → `stable` (everyone). A model moves one step only after its gate passes.

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| ML-01 | Dataset layout and versioning: COCO-format datasets in object storage, version tags, a dataset card per version (sources, licence, consent, classes, image counts, day/night split) | CV | 1 | Must | VID-03 | Dataset `ppe-v1` has a card and can be rebuilt from its sources |
| ML-02 | Labelling tool: CVAT self-hosted on staging (or Roboflow while small), class lists per model, written labelling guide with picture examples (what counts as "helmet", partly hidden objects, minimum size) | CV, DO | 1.5 | Must | SET-09 | Two labellers given the same 50 images agree on 90%+ of boxes |
| ML-03 | Frame extraction: pull varied frames from clips (scene change, every N seconds), remove near-duplicates (perceptual hash), balance day, night and crowded scenes | CV | 1 | Must | ML-01 | 1 hour of footage gives about 300 varied frames |
| ML-04 | Automatic pre-labelling with Grounding DINO or Florence-2 from text prompts ("hard hat", "forklift", "mop"), humans only correct | CV | 2 | Should | ML-02 | Labelling time per image drops by half against labelling from scratch |
| ML-05 | Training pipeline: one command fine-tunes RF-DETR (Nano or Small) on a dataset version using a rented GPU; augmentations for low light, IR grey, blur and glare; fixed random seed; metrics (mAP, per-class AP) logged to MLflow (self-hosted); GPU stops automatically when training ends | CV | 3 | Must | ML-01 | `ppe-v1` trains in under 2 hours for under SAR 15 of GPU time |
| ML-06 | Release gate: evaluate on a held-out image set and run the full video harness with the new model; release only if no class gets worse beyond 2 points and the target class improves | CV | 1.5 | Must | ML-05, VID-05 | Gate report attached to every model release |
| ML-07 | Export per hardware tier: ONNX for CPU and RTX boxes; TensorRT FP16 engines built on a Jetson; INT8 with 500 calibration images from real sites where accuracy holds; manifest with checksum and licence | CV | 2 | Must | ML-05, HW-02 | Same model gives matching results on laptop, mini-PC and Jetson |
| ML-08 | Model registry and rollout: `model_releases` in the database plus files in storage; channels dev, staging, canary, stable; rollout to device groups; one-click rollback | BE, CV | 2 | Must | CLD-04, EDG-06 | A model is rolled to the office box, then rolled back, from the admin console |
| ML-09 | Feedback-to-training loop: every "False alarm" and every reported miss sends its frames to a labelling queue weekly; a retrain cycle runs monthly | CV | 1.5 | Should | CLD-11, ML-02 | First retrain built from pilot feedback |
| ML-10 | Labelling capacity: decide between contract labellers and internal QA; budget for about 10,000 boxes for the V1 classes; 10% of each batch double-checked | PO, CV | 1 | Should | ML-02 | Labels for PPE, hairnet and forklift delivered on schedule |
| ML-11 | Licence register for training data: every image source and its licence; non-commercial datasets excluded automatically from builds | CV | 0.5 | Must | ML-01 | Build fails if a dataset contains a source without a commercial-use licence |
| ML-12 | Privacy in training data: client footage stays in our private storage; a client deletion request removes their frames from all datasets and the next model release is trained without them | CV, DO | 1 | Must | ML-01, VID-11 | Deletion runbook tested on a dummy client |
| ML-13 | AI-check prompt library and test set: one prompt per verified rule type; 200 stored snapshots with a known yes/no answer; accuracy, delay and cost per prompt version tracked; same test run on Claude Haiku and a self-hosted Qwen3-VL to decide when self-hosting pays | CV | 2 | Must | CLD-12 | Prompt changes cannot merge if accuracy on the test set drops |
| ML-14 | Documentation: how to add a new detectable object end to end (data → labels → training → gate → export → release), written so a mid-level developer can follow it with Claude Code | CV | 1 | Should | ML-08 | A second person trains and releases a model by following the document |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
