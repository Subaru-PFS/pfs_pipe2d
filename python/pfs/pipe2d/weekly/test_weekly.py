import os
import sys
import unittest

import numpy as np

import lsst.utils.tests
import lsst.afw.image.testUtils
from lsst.daf.persistence import Butler

from pfs.datamodel import PfsDesign, calculatePfsVisitHash
from pfs.drp.stella.tests.utils import classParameters
from pfs.pipe2d.weekly.utils import getBrnVisits, getBmnVisits

display = None
weeklyRaw = None
weeklyRerun = None


@classParameters(configuration=("brn", "bmn"))
class ProductionTestCase(lsst.utils.tests.TestCase):
    def setUp(self):
        self.butler = Butler(os.path.join(weeklyRerun, "pipeline", self.configuration, "pipeline"))
        self.visits = dict(brn=getBrnVisits, bmn=getBmnVisits)[self.configuration]()
        self.design = PfsDesign.read(1, weeklyRaw)

    def tearDown(self):
        del self.butler

    def testVisitProducts(self):
        """Test that visit products exist"""
        for visit in self.visits:
            for arm in self.configuration:
                self.assertTrue(self.butler.datasetExists("pfsArm", visit=visit, arm=arm))
            self.assertTrue(self.butler.datasetExists("pfsMerged", visit=visit))
            config = self.butler.get("pfsConfig", visit=visit, arm=arm)
            for target in config:
                self.assertTrue(self.butler.datasetExists("pfsSingle", target.identity, visit=visit))

    def testObjectProducts(self):
        """Test that object products exist"""
        for target in self.design:
            dataId = target.identity.copy()
            dataId["nVisit"] = len(self.visits)
            dataId["pfsVisitHash"] = calculatePfsVisitHash(self.visits)
            self.assertTrue(self.butler.datasetExists("pfsObject", dataId), msg=str(dataId))

    def testSpectra(self):
        """Test that spectra files can be read, and they are reasonable"""
        for visit in self.visits:
            config = self.butler.get("pfsConfig", visit=visit)
            spectra = self.butler.get("pfsMerged", visit=visit)
            badMask = spectra.flags.get("NO_DATA", "BAD_FLAT", "INTRP")
            for fiberId in config.fiberId:
                with self.subTest(visit=visit, fiberId=fiberId):
                    index = np.where(spectra.fiberId == fiberId)[0]
                    mask = spectra.mask[index]
                    select = (mask & badMask) == 0

                    self.assertGreater(select.sum(), 0.75*len(mask), "Too many masked pixels")
                    self.assertFalse(np.all(spectra.sky[index][select] == 0))
                    self.assertTrue(np.all(spectra.variance[index][select] > 0))

    @lsst.utils.tests.debugger(Exception)
    def testObjects(self):
        """Test that object files can be read, and they are reasonable"""
        for target in self.design:
            with self.subTest(**target.identity):
                spectrum = self.butler.get("pfsObject", target.identity, nVisit=len(self.visits),
                                           pfsVisitHash=calculatePfsVisitHash(self.visits))
                badMask = spectrum.flags.get("NO_DATA")
                select = (spectrum.mask & badMask) == 0
                self.assertGreater(select.sum(), 0.75*len(spectrum), "Too many masked pixels")
                self.assertFalse(np.all(spectrum.sky[select] == 0))
                self.assertTrue(np.all(spectrum.variance[select] > 0))


@classParameters(
    arms=("brn", "m"),
    visit=(39, 40),
)
class ArcTestCase(lsst.utils.tests.TestCase):
    def setUp(self):
        self.butler = Butler(os.path.join(weeklyRerun, "calib", self.arms, "detectorMap"))

    def tearDown(self):
        del self.butler

    def testResiduals(self):
        """Test that wavelength fit residuals are reasonable"""
        for arm in self.arms:
            detMap = self.butler.get("detectorMap", visit=self.visit, arm=arm)
            lines = self.butler.get("arcLines", visit=self.visit, arm=arm)
            for fiberId in set(lines.fiberId):
                with self.subTest(arm=arm, fiberId=fiberId):
                    select = lines.fiberId == fiberId
                    num = select.sum()
                    self.assertGreater(num, 20)

                    fitWavelength = detMap.findWavelength(fiberId, lines.y[select].astype(np.float32))
                    residual = lines.wavelength[select] - fitWavelength
                    lq, median, uq = np.percentile(residual, (25.0, 50.0, 75.0))
                    self.assertFloatsAlmostEqual(median, 0.0, atol=5.0e-2)
                    self.assertFloatsAlmostEqual(0.741*(uq - lq), 0.0, atol=3.0e-2)


class TestMemory(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    from argparse import ArgumentParser
    parser = ArgumentParser(__file__)
    parser.add_argument("--display", help="Display backend")
    parser.add_argument("--profile", action="store_true", help="Profile tests?")
    parser.add_argument("--raw", required=True, help="Path to raw data")
    parser.add_argument("--rerun", required=True, help="Path to base of weekly rerun")
    args, argv = parser.parse_known_args()
    display = args.display
    weeklyRaw = args.raw
    weeklyRerun = args.rerun

    setup_module(sys.modules["__main__"])

    if args.profile:
        import cProfile
        import pstats
        profile = cProfile.Profile()
        profile.enable()

    unittest.main(failfast=True, argv=[__file__] + argv, exit=not args.profile)

    if args.profile:
        profile.disable()
        stats = pstats.Stats(profile)
        stats.sort_stats("cumulative")
        stats.print_stats(30)
