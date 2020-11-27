import itertools

import lsst.utils.tests

from pfs.datamodel import PfsDesign
from pfs.utils.dummyCableB import DummyCableBDatabase, makePfsDesign, main
from pfs.drp.stella.tests import runTests, temporaryDirectory

display = None


class DummyCableBTestCase(lsst.utils.tests.TestCase):
    """Test functionality of pfs.utils.dummyCableB"""
    def setUp(self):
        self.db = DummyCableBDatabase()

    def testPython(self):
        """Test python interface"""
        pfsDesignId = {}
        # Not testing all possible combinations, as that would take too long.
        combinations = sum((list(itertools.combinations(self.db.names, nn)) for nn in range(1, 4)), [])
        for names in combinations:
            ident = self.db.getHash(*names)
            # Test uniqueness of different combinations of setups
            self.assertNotIn(ident, pfsDesignId)
            pfsDesignId[ident] = set(names)

            # Test that ordering is unimportant
            fiberIds = self.db.getFiberIds(*names)
            for nn in itertools.permutations(names, len(names)):
                self.assertEqual(self.db.getHash(*nn), ident)
                self.assertFloatsEqual(self.db.getFiberIds(*nn), fiberIds)

            # Test makePfsDesign
            design = makePfsDesign(ident, fiberIds)
            self.assertFloatsEqual(design.fiberId, fiberIds)

    def testCommandLine(self):
        """Test command-line interface

        We don't actually run the executable (because that involves overhead
        to set paths, etc), but we run what the executable runs, so we're
        checking the argument parsing, etc.
        """
        for names in itertools.combinations(self.db.names, 2):  # Just two at a time, for speed
            pfsDesignId = self.db.getHash(*names)
            with temporaryDirectory() as tempDir:
                argv = ["--directory", tempDir] + list(names)
                main(argv)
                design = PfsDesign.read(pfsDesignId, tempDir)
                self.assertFloatsEqual(design.fiberId, self.db.getFiberIds(*names))


class TestMemory(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    runTests(globals())
