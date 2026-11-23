# Notebooks

Each notebook clones the repo at a named branch and runs on a hosted GPU
(Colab or Kaggle), so nothing here depends on a local setup.

| Notebook | What it does |
| --- | --- |
| `01_sen1floods11_sanity_check.ipynb` | Check the Sen1Floods11 download and splits before training |
| `02_train_unet_resnet50.ipynb` | Train the CNN source model (#19) |
| `03_train_unet_maxvit.ipynb` | Train the transformer source model (#20) |
| `04_labelling_colab.ipynb` | Prepare chips for hand labelling (#28) |

The two training notebooks are numbered together because they are the same step
of the project with a different encoder, and their results are meant to be read
side by side.

Notebooks are committed **with their outputs**, so the numbers in a run can be
read without rerunning it. Each run also copies its artefacts into
`reports/<run name>/`: `runs/` is gitignored, so a run that is not copied out
leaves no trace in git.
