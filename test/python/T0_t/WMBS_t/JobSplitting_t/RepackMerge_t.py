#!/usr/bin/env python
"""
_RepackMerge_t_

RepackMerge job splitting test

"""

import unittest
import threading
import logging
import time

from WMCore.WMBS.File import File
from WMCore.WMBS.Fileset import Fileset
from WMCore.WMBS.Subscription import Subscription
from WMCore.WMBS.Workflow import Workflow
from WMCore.DataStructs.Run import Run

from WMCore.DAOFactory import DAOFactory
from WMCore.JobSplitting.SplitterFactory import SplitterFactory
from WMCore.Services.UUID import makeUUID
from WMQuality.TestInit import TestInit


class RepackTest(unittest.TestCase):
    """
    _RepackTest_

    Test for Repack job splitter
    """

    def setUp(self):
        """
        _setUp_

        """
        self.testInit = TestInit(__file__)
        self.testInit.setLogging()
        self.testInit.setDatabaseConnection()

        self.testInit.setSchema(customModules = ["T0.WMBS"])

        self.splitterFactory = SplitterFactory(package = "T0.JobSplitting")

        myThread = threading.currentThread()
        daoFactory = DAOFactory(package = "T0.WMBS",
                                logger = logging,
                                dbinterface = myThread.dbi)

        myThread.dbi.processData("""INSERT INTO wmbs_location
                                    (id, site_name, se_name)
                                    VALUES (wmbs_location_SEQ.nextval, 'SomeSite', 'SomeSE')
                                    """, transaction = False)

        insertRunDAO = daoFactory(classname = "RunConfig.InsertRun")
        insertRunDAO.execute(binds = { 'RUN' : 1,
                                       'TIME' : int(time.time()),
                                       'HLTKEY' : "someHLTKey" },
                             transaction = False)

        insertLumiDAO = daoFactory(classname = "RunConfig.InsertLumiSection")
        insertLumiDAO.execute(binds = { 'RUN' : 1,
                                        'LUMI' : 1 },
                              transaction = False)
        insertLumiDAO.execute(binds = { 'RUN' : 1,
                                        'LUMI' : 2 },
                              transaction = False)
        insertLumiDAO.execute(binds = { 'RUN' : 1,
                                        'LUMI' : 3 },
                              transaction = False)
        insertLumiDAO.execute(binds = { 'RUN' : 1,
                                        'LUMI' : 4 },
                              transaction = False)

        insertStreamDAO = daoFactory(classname = "RunConfig.InsertStream")
        insertStreamDAO.execute(binds = { 'STREAM' : "A" },
                                transaction = False)

        insertStreamFilesetDAO = daoFactory(classname = "RunConfig.InsertStreamFileset")
        insertStreamFilesetDAO.execute(1, "A", "TestFileset1")

        fileset1 = Fileset(name = "TestFileset1")
        self.fileset2 = Fileset(name = "TestFileset2")
        fileset1.load()
        self.fileset2.create()

        workflow1 = Workflow(spec = "spec.xml", owner = "hufnagel", name = "TestWorkflow1", task="Test")
        workflow2 = Workflow(spec = "spec.xml", owner = "hufnagel", name = "TestWorkflow2", task="Test")
        workflow1.create()
        workflow2.create()

        self.subscription1  = Subscription(fileset = fileset1,
                                           workflow = workflow1,
                                           split_algo = "Repack",
                                           type = "Repack")
        self.subscription2  = Subscription(fileset = self.fileset2,
                                           workflow = workflow2,
                                           split_algo = "RepackMerge",
                                           type = "RepackMerge")
        self.subscription1.create()
        self.subscription2.create()

        myThread.dbi.processData("""INSERT INTO wmbs_workflow_output
                                    (WORKFLOW_ID, OUTPUT_IDENTIFIER, OUTPUT_FILESET)
                                    VALUES (%d, 'SOMEOUTPUT', %d)
                                    """ % (workflow1.id, self.fileset2.id),
                                 transaction = False)

        # keep for later
        self.insertSplitLumisDAO = daoFactory(classname = "JobSplitting.InsertSplitLumis")

        # default split parameters
        self.splitArgs = {}
        self.splitArgs['minSize'] = 2.1 * 1024 * 1024 * 1024
        self.splitArgs['maxSize'] = 4.0 * 1024 * 1024 * 1024
        self.splitArgs['maxEvents'] = 100000000
        self.splitArgs['maxInputFiles'] = 1000
        self.splitArgs['maxEdmSize'] = 20 * 1024 * 1024 * 1024
        self.splitArgs['maxOverSize'] = 10 * 1024 * 1024 * 1024

        return

    def tearDown(self):
        """
        _tearDown_

        """
        self.testInit.clearDatabase()

        return

    def deleteSplitLumis(self):
        """
        _deleteSplitLumis_

        """
        myThread = threading.currentThread()

        myThread.dbi.processData("""DELETE FROM lumi_section_split_active
                                    """,
                                 transaction = False)

        return

    def test00(self):
        """
        _test00_

        Test that the job name prefix feature works

        Test max edm size threshold for single lumi

        small lumi, followed by over-large lumi
        expect 1 job for small lumi and 4 jobs for over-large

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(2 * lumi):
                newFile = File(makeUUID(), size = 1000 * lumi * lumi, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxEdmSize'] = 13000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 3,
                         "ERROR: JobFactory didn't create three jobs")

        job = jobGroups[0].jobs[0]
        self.assertTrue(job['name'].startswith("RepackMerge-"),
                        "ERROR: Job has wrong name")

        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        job = jobGroups[0].jobs[1]
        self.assertEqual(len(job.getFiles()), 3,
                         "ERROR: Job does not process 3 files")

        job = jobGroups[0].jobs[2]
        self.assertEqual(len(job.getFiles()), 1,
                         "ERROR: Job does not process 1 file")

        return

    def test01(self):
        """
        _test01_

        Test max size threshold for single lumi

        small lumi, followed by large lumi
        expect 1 job for small lumi and 1 job for large

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000 * lumi, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxSize'] = 3000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 2,
                         "ERROR: JobFactory didn't create two jobs")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        job = jobGroups[0].jobs[1]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

    def test02(self):
        """
        _test02_

        Test max event threshold for single lumi

        small lumi, followed by large lumi
        expect 1 job for small lumi and 1 job for large

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000, events = 100 * lumi)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxEvents'] = 300
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 2,
                         "ERROR: JobFactory didn't create two jobs")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        job = jobGroups[0].jobs[1]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

    def test03(self):
        """
        _test03_

        Test max input files threshold for single lumi

        small lumi, followed by large lumi
        expect 1 job for small lumi and 1 job for large

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(lumi * 2):
                newFile = File(makeUUID(), size = 1000, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxInputFiles'] = 3
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 2,
                         "ERROR: JobFactory didn't create two jobs")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        job = jobGroups[0].jobs[1]
        self.assertEqual(len(job.getFiles()), 4,
                         "ERROR: Job does not process 4 files")

        return

    def test04(self):
        """
        _test04_

        Test max size threshold for multi lumi

        3 same size lumis

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2,3]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        mySplitArgs['minSize'] = 3000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxSize'] = 5000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 4,
                         "ERROR: Job does not process 4 files")

        self.fileset2.markOpen(False)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

    def test05(self):
        """
        _test05_

        Test max event threshold for multi lumi

        3 same size lumis

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2,3]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        mySplitArgs['minSize'] = 3000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxEvents'] = 500
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 4,
                         "ERROR: Job does not process 4 files")

        self.fileset2.markOpen(False)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

    def test06(self):
        """
        _test06_

        Test max input files threshold for multi lumi

        3 same size lumis

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2,3]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        mySplitArgs['minSize'] = 3000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 0,
                         "ERROR: JobFactory should have returned no JobGroup")

        mySplitArgs['maxInputFiles'] = 5
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 4,
                         "ERROR: Job does not process 4 files")

        self.fileset2.markOpen(False)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

    def test07(self):
        """
        _test07_

        Test over merge

        one small lumi, one large lumi (small below min size,
        large below max size, but both together above max size)

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000 * lumi * lumi, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        mySplitArgs['minSize'] = 3000
        mySplitArgs['maxSize'] = 9000
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 4,
                         "ERROR: Job does not process 4 files")

        return

    def test08(self):
        """
        _test08_

        Test under merge (over merge size threshold)

        one small lumi, one large lumi (small below min size,
        large below max size, but both together above max size)

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000 * lumi * lumi, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        mySplitArgs['minSize'] = 3000
        mySplitArgs['maxSize'] = 9000
        mySplitArgs['maxOverSize'] = 9500
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        self.fileset2.markOpen(False)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

    def test09(self):
        """
        _test09_

        Test under merge (over merge event threshold)

        one small lumi, one large lumi (small below min size,
        large below max size, but both together above max size)

        """
        mySplitArgs = self.splitArgs.copy()

        for lumi in [1,2]:
            for i in range(2):
                newFile = File(makeUUID(), size = 1000 * lumi * lumi, events = 100)
                newFile.addRun(Run(1, *[lumi]))
                newFile.setLocation("SomeSE", immediateSave = False)
                newFile.create()
                self.fileset2.addFile(newFile)
        self.fileset2.commit()

        jobFactory = self.splitterFactory(package = "WMCore.WMBS",
                                          subscription = self.subscription2)

        mySplitArgs['minSize'] = 3000
        mySplitArgs['maxSize'] = 9000
        mySplitArgs['maxEvents'] = 300
        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        self.fileset2.markOpen(False)

        jobGroups = jobFactory(**mySplitArgs)

        self.assertEqual(len(jobGroups), 1,
                         "ERROR: JobFactory didn't return one JobGroup")

        self.assertEqual(len(jobGroups[0].jobs), 1,
                         "ERROR: JobFactory didn't create one job")

        job = jobGroups[0].jobs[0]
        self.assertEqual(len(job.getFiles()), 2,
                         "ERROR: Job does not process 2 files")

        return

if __name__ == '__main__':
    unittest.main()