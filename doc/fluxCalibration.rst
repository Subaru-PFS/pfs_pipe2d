Flux calibration for PFS
========================

Flux calibration has two objectives:

1. Relate counts on the detectors to physical fluxes
so that line fluxes can be measured and associated with physical processes.

2. Correct for telluric absorption features in the spectrum,
which can mask important spectral features and bias continuum measurements.

Here we outline a proposed strategy for flux calibration for PFS,
along with an estimation of what work needs to be done to support this.


Strategy
--------

Flux calibration requires flat-fielding and
then determining a response function that maps counts on the detector to physical fluxes.

There are multiple strategies that we could choose to determine the response function:

1. Photometric pseudo-standards in the field:
using broadband photometry (``grizyJH`` or similar) of fiber targets would allow us
to use the vast majority of fiber targets in the calibration,
but the coarse wavelength resolution does not allow us to easily correct for telluric absorption.

2. Spectrophotometric standards in independent exposures:
this is the classical approach used for calibrating longslit observations,
whereby observations of a standard star with a well-known spectrum
are used to correct observations taken at a similar time.
This is a simple procedure, but is subject to errors
due to not observing through the same atmosphere as the science observations,
and it requires additional observations and therefore a reduced observing efficiency.

3. Spectrophotometric pseudo-standards in the field:
this is the approach used by SDSS [#]_.
18 fibers of the 640 were dedicated to F dwarfs (8), F subdwarfs (8) and hot subdwarfs (2) [#]_.
The flux of these reference stars are known from broadband imaging,
while the spectra can be determined from fitting model or library spectra.

.. [#] See the Early Data Release paper (Stoughton et al., ``2002AJ....123..485S``),
   sections 4.8.5 and 4.10.1;
   see also `the idlspec2d code <http://das.sdss.org/software/idlspec2d/v5_3_12/>`_.

.. [#] F dwarfs have smooth spectra suitable for correcting the telluric features in the red,
   while the hot subdwarfs are good in the blue.
   The F subdwarfs were reddening standards (for measuring the dust reddening from the Milky Way),
   but were also used for measuring the telluric absorption.

We will follow the example of SDSS and use spectrophotometric pseudo-standards in the field,
as the use of standards in the field means that the standards and targets
are observed through the exact same atmospheric column,
allowing for the most accurate removal of telluric features.

If necessary, after calibration with spectrophotometric pseudo-standards,
we could apply small corrections using broadband photometry (photometric pseudo-standards).


Flat fielding
~~~~~~~~~~~~~

Before we can relate the flux measurements from different fibers,
they must first be calibrated relative to one another.
This is the purpose of flat-fielding [#]_.

.. [#] Flat-fielding has another purpose,
   which is to correct for pixel-to-pixel sensitivity variations in the spatial dimension within each fiber.
   However, the technique outlined here will correct for that as well.

We will extract the spectrum from each fiber in the flat-field,
and determine the mean spectrum of all the fibers [#]_;
this will be our reference spectrum.
We then make a synthetic image using this reference spectrum and the known fiber profile,
and divide our flat-field image by this synthetic reference image.
The result is an image of the ratio between the observed flat-field spectrum and the mean flat-field spectrum.

.. [#] It's not clear to me if it's necessary to do this in wavelength space,
   or if row-by-row is sufficient.
   Row-by-row is preferred if it doesn't make a large difference,
   since it is a much simpler operation;
   but if there are large wavelength shifts between the individual spectra then it may not be accurate.

The flat-field image, :math:`F(i, \lambda, x)`, is:

.. math::
   F(i, \lambda, x) = f(\lambda).\Psi(i, \lambda, x)

where :math:`f(\lambda)` is the spectrum of the flat-field lamp
and :math:`\Psi(i, \lambda, x)` is the response of the detector
as a function of fiber :math:`i`, wavelength :math:`\lambda`,
and column (spatial dimension) :math:`x`.

Then our ratio image is:

.. math::
   R(i, \lambda, x) = F(i, \lambda, x)/\bar{F(\lambda)} \\
   R(i, \lambda, x) = f(\lambda).\Psi(i, \lambda, x)/\bar{F(\lambda)} \\
   R(i, \lambda, x) = r(\lambda).\Psi(i, \lambda, x)

Here, :math:`\bar{F(\lambda)}` is the mean instrumental flat-field spectrum
(extracted over the spatial dimension and averaged over fibers).
Since that is purely a function of wavelength,
we can pull it and :math:`f(\lambda)` into a common spectral function,
:math:`r(\lambda)`, which we'll call the "response function".

Science exposures are the response of the detector to the science spectra, :math:`s(i, \lambda)`:

.. math::
   S(i, \lambda, x) = s(i, \lambda).\Psi(i, \lambda, x)

When we flat-field the science image using the ratio image, we get:

.. math::
   S(i, \lambda, x)/R(i, \lambda, x) = s(i, \lambda)/r(\lambda)

Notice that this flat-fielded image, :math:`S/R`, consists of the science spectra
divided by a function that is entirely a function of wavelength.
This means that response differences between fibers
(and in the spatial dimension within a fiber)
have been removed.
Flux calibration is now reduced to finding the :math:`r(\lambda)`.

One detail to consider is the spectral normalisation of the response function.
Before dividing the observed flat fields by the mean of the observed flat spectrum,
we could fit a function to the observed flat spectrum and normalise the spectrum by that;
then the ratio image would have a much stronger variation as a function of wavelength
(e.g., due to the dichroics and the grating blaze)
and look much more like the fiber flat image.
This change in normalisation would be swept up into the :math:`r(\lambda)`,
so it doesn't affect flux calibration downstream.
However, dividing science images by an image constructed in that way
would produce an image where the number of counts
is not simply related to the number of photons hitting the detector,
which is somewhat counter-intuitive.
We therefore prefer the scheme outlined above.

Multiple ratio images constructed in this way can be coadded to build up signal
or with the slit offset in the spatial dimension
in order to gain greater signal-to-noise in the wings of the fiber profiles.

With a bit of care in the parallelism,
it should be possible to construct ratio images that relate
not just all the fibers in a spectrograph,
but all fibers in all of the spectrographs.
The advantage of doing this would be that we only need to solve
for a single response function for the entire exposure.


Response function from spectrophotometric pseudo-standards
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Following flat-fielding, flux calibration is reduced to solving for the "response function".
This is a function of wavelength that relates (flat-fielded) counts on the detector to physical fluxes.
The physical fluxes will come from objects observed in the same exposure,
for which we have spectrophotometry.
Although spectrophotometric standards are sparse on the sky,
we can use "pseudo-spectrophotometric standards" by observing objects
with simple (but unknown) spectra and measured broadband photometry,
as the photometric measurements allow us to determine the spectra
and therefore the response function.
The particular pseudo-spectrophotometric standards we choose are F dwarfs,
since they have smooth spectra in the red that will allow us to remove the telluric absorption.

The brute force approach to measuring the response function would be to
fit the spectral type and luminosity to the broadband photometry for each star,
use the best fit to determine the response function from the observed spectrum;
and then average the response functions so measured from all the available stars.
A more sophisticated approach would be to make a simultaneous fit of the response function
to the observed spectrum and broadband photometry of all stars,
marginalising over the spectral type and other nuisance parameters.
We propose to first implement the brute force approach (because of its simplicity)
and implement the more sophisticated approach as time allows
or if it becomes necessary to meet performance goals.

Stellar templates could come from the Pickles catalog [#]_, as for SDSS,
or from a newer stellar spectroscopic atlas.

.. [#] Pickles, ``1998PASP..110..863P``,
   `access catalog here <http://www.stsci.edu/hst/observatory/crds/pickles_atlas.html>`_.

A straightforward model for the response function would be a polynomial in wavelength.
We propose to use empirical corrections [#]_ over the wavelengths affected by the telluric absorption.
It's possible that the telluric absorption can be modelled by a function with a small number of parameters
(e.g., water column, atmospheric pressure, ...?)
that might be extracted from an atmospheric modelling code (e.g., MODTRAN)
or previous spectroscopic observations;
this is another update option for the future, if time allows and/or performance suffers.

.. [#] I.e., a set of delta functions in wavelength as the basis set.


Tweak with broadband photometry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We might well believe that the spectrum of the flat-field could vary from fiber to fiber [#]_.
If that is the case, then we can apply small corrections by mapping response variations over the focal plane.
Using broadband photometry, we can use any fiber with decent signal-to-noise as a calibration source.
This would involve integrating the spectra over the photometric bandpasses [#]_,
and deriving a correction function (as a function of wavelength and position on the focal plane).

.. [#] For example, :math:`f(\lambda)` is really :math:`f(i, \lambda)`,
   which is to say that the scattering function for the flat-field screen
   is a function of wavelength as well as angle.
   Given the fact that the screen used for flat-fielding at Subaru is far from ideal,
   this may well be the case.

.. [#] When integrating, it will be important to pay attention to the units used.
   The spectral fluxes are to be in nanoJanskies, while the wavelengths are in nanometres.


Work
----

The following work needs to be done in order to realise the above proposal.
If this work is approved, the following items might be used as Jira issues.


Baseline
~~~~~~~~

1. Flat fielding (`PIPE2D-290`_):
we need to implement the above prescription for creating our flat fields.
Currently, the profiles for individual fibers are normalised separately,
which means that calibrations derived from one fiber cannot be simply applied to others.

.. _PIPE2D-290: https://pfspipe.ipmu.jp/jira/browse/PIPE2D-290

2. Obtain spectra of spectrophotometric pseudo-standards.
This new ``Task`` will use the redesigned ``PfsConfig`` to identify fibers with calibration sources,
along with their photometric measurements,
and fit spectral templates.
The result will be a set of observed spectra with associated physical spectra.

3. Measure and apply response function.
This new ``Task`` will measure the response function from each standard,
and average the result to obtain a mean response function
which will be applied to all spectra from the exposure.

4. Integrate the new flux calibration ``Task``\ s
into a system that will extract and calibrate science exposures,
and add high-level tests of the functionality.


Upgrade options
~~~~~~~~~~~~~~~

1. Refactor flat construction to relate fibers on different spectrographs.
Currently (and even following `PIPE2D-290`_),
flat-fields are normalised on individual CCDs
rather than putting all spectrographs on the same normalisation.
This means that the flux calibration has to be done separately for each spectrograph,
which introduces opportunity for errors to creep in.

2. Simultaneous fit of response function.
This would fit all the observed spectra and broadband photometry of the calibration sources simultaneously,
marginalising over the spectral type and other nuisance parameters,
yielding a single response function.
This ``Task`` would be an alternative implementation of the "Measure and apply response function", above.

3. Use parametric fit for telluric absorption.
We could determine a parametric model for the telluric absorption bands
from an atmospheric modelling code (MODTRAN) or PCA of existing spectra,
and use this in the place of the empirical model in the baseline plan.

4. Tweak response function using photometric pseudo-standards.
This new ``Task`` would fit a low-order correction to the response function
using broadband photometry of all sources in the field.
This fit could be a function of position on the focal plane.


Requirements on data model
--------------------------

The plan for flux calibration places the following requirements on the data model:

1. We need to be able to identify fibers to be used for flux calibration.
Flux calibration cannot be done using just any source as the reference,
so we need to be able to identify the suitable fibers.
We expect this will use the redesigned ``PfsConfig``.

2. Fibers need to have magnitudes and bandpass names.
This is especially required for the fibers used for flux calibration,
but if it is applied to all (or, at least, a majority of) fibers,
we could use them to tweak the response function.
We expect this will use the redesigned ``PfsConfig``.

3. We need to have the bandpass transmission functions.
In order to integrate the spectra over the bandpass, we need to know the bandpass.
This means that no bandpass should be specified in the ``PfsConfig``
for which we do not have the bandpass transmission function.

4. We need to have template spectra available.
The template spectra need to span the spectral space of the objects used for flux calibration.
