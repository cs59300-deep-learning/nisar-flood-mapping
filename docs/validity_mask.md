# NISAR validity mask

Use the GCOV product's own `mask` layer to decide which pixels participate in
analysis. For the granules in this project, a sample is valid only when its
mask code equals `1`. Code `0` denotes a partially focused or invalid sample,
`255` denotes locations outside the radar acquisition extent, and other
nonzero codes identify subswaths. Therefore, `mask != 0` incorrectly includes
invalid and out-of-acquisition pixels.

Call `apply_validity_mask(samples, mask)` before calculating any statistics or
creating downstream features. It returns a NumPy masked array, so use
masked-aware reductions (for example `numpy.ma.mean`); converting it to a
plain array before reducing would discard the validity information. Samples
are expected to have spatial dimensions first, and the mask must match those
two dimensions. The project currently has no GCOV reader or statistics
pipeline, so code that reads a granule must pass its product `mask` dataset to
these helpers before computing statistics.

Record `granule_validity_report(granule_id, mask)` for every granule. The
`valid_pixel_fraction` field is the number of pixels with mask code `1`
divided by the total number of mask pixels. To document agreement with the
former zero/floor heuristic, pass its boolean validity map as
`zero_heuristic_valid`; the report includes the valid counts for both methods
and the fraction of pixels on which they agree. The helper deliberately takes
that map as input: the legacy floor threshold belongs to the preprocessing
that generated it and is not encoded in the NISAR mask specification.

```python
masked_backscatter = apply_validity_mask(backscatter, gcov_mask)
mean_backscatter = np.ma.mean(masked_backscatter)
qa = granule_validity_report(granule_id, gcov_mask)
```
