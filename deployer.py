import os, sys
import ConfigParser
import sysif.subproc
import sysif.net
import re
import logging
import xml.etree.ElementTree as ET
import time
import getopt
import tarfile
import zipfile
import copy
import zipfile
import glob
import os

from datetime import datetime

"""
B/W Deploy Helper Script

written by yongki82.kim@samsung.com
last updated at Mar.30, 2011
"""

log_handlers = []
config_file_name='deployer.ini'
target_config_file_name='targets.ini'


class CaseSensitiveConfigParser(ConfigParser.RawConfigParser):
    def optionxform(self, optionstr):
        return optionstr

def GetTargets(target_settings, target_name, log):
    target_items = target_settings.sections()

    target_items.pop(target_items.index('Default'))
    target_items.pop(target_items.index('Bindings'))
    target_items.pop(target_items.index('Service Settings'))
    target_items.pop(target_items.index('Deployment'))
    target_items.pop(target_items.index('Targets'))

    target_str = target_settings.get('Targets', target_name)
    targets = []

    if target_str == '*':
        targets = target_items
    else:
        for target in target_str.split(' '):
            if target in target_items:
                targets.append(target)
            else:
                log.error('Invalid target: ' + target)
                sys.exit(1)
    #targets.sort()
    return targets

# Patch for deployment at TIBCO BusinessWorks 5.1 environment.
def HackVersionConstraint(file_path):
    path_parts = file_path.split(os.path.sep)
    file_name = path_parts[-1]
    path_name = os.path.sep.join(path_parts[:-1])

    zin = zipfile.ZipFile (file_path, 'r')
    zout = zipfile.ZipFile (file_path + ".tmp", 'w', zipfile.ZIP_DEFLATED)
    par_file_path = file_path.replace(".ear", ".par")
    par_file_name = file_name.replace(".ear", ".par")

    for item in zin.infolist():
        buffer = zin.read(item.filename)
        if (item.filename == par_file_name):
            with file(par_file_path, 'wb') as fp:
                fp.write(buffer)

            pin = zipfile.ZipFile (par_file_path, 'r')
            pout = zipfile.ZipFile (par_file_path + ".tmp", "w", zipfile.ZIP_DEFLATED)

            for item2 in pin.infolist():
                buffer = pin.read(item2.filename)
                if (item2.filename == "TIBCO.xml"):
                    pout.writestr(item2.filename, buffer.replace("5.3.0", "5.0.0"))
                else:
                    pout.writestr(item2.filename, buffer)
            pin.close()
            pout.close()
            
            with file(par_file_path+".tmp", "rb") as fp:
                zout.writestr(par_file_name, fp.read())
        else:
            zout.writestr(item.filename, buffer)
    zout.close()
    zin.close()

    try:
        os.remove(par_file_path)
        os.remove(par_file_path+".tmp")
        os.remove(file_path)
        os.rename(file_path+".tmp", file_path)
    except:
        pass


# Beautify ElementTree
def IndentElem(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            IndentElem(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

# Generage AppManage Batch Script
def GenerateBatchScript(batch_script_path, targets):
    tree = ET.ElementTree(ET.Element('apps'))
    root = tree.getroot()

    appname_tmp    = target_settings.get('Default', 'appname')
    deployname_tmp = target_settings.get('Default', 'deployname')

    for target in targets:
        appname        = appname_tmp % locals()
        attr = {}
        attr['name'] = deployname_tmp % locals()
        attr['ear']  = appname + '.ear'
        attr['xml']  = appname + '.xml'

        ET.SubElement(root, 'app', attr)

    IndentElem(root)
    with file(batch_script_path, 'w+') as fp:
        fp.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(fp, 'utf-8')

def PackDeployFiles(tar_file_path, build_date, targets, deploy_dir, config, deploy_desc=''):
    os.chdir(deploy_dir)

    tar = tarfile.open(tar_file_path, "w")
    tar.add('AppManage.batch', build_date + deploy_desc + "/" + 'AppManage.batch')

    with file('deploy.sh', 'w+') as fp:
        fp.write('AppManage -batchDeploy -user %(admin_user)s -pw %(admin_pass)s -domain %(domain)s -dir %(remote_dir)s/%(build_date)s%(deploy_desc)s' % config)

    tar.add('deploy.sh', build_date + deploy_desc +  "/" + 'deploy.sh')

    for target in targets:
        appname_tmp = target_settings.get('Default', 'appname')
        appname     = appname_tmp % locals()

        tar.add(appname + '.ear', build_date + deploy_desc + "/" + appname + ".ear")
        tar.add(appname + '.xml', build_date + deploy_desc + "/" + appname + ".xml")

    tar.close()

"""
Following scheme ordering is very important to run AppManage correctly.
(I don't know why...)
"""
ordering_list_binding = [
    "machine",
    "contact"
    "description",
    "product/type",
    "product/version",
    "product/location",
    "setting/startOnBoot",
    "setting/enableVerbose",
    "setting/maxLogFileSize",
    "setting/maxLogFileCount",
    "setting/threadCount",
    "setting/java/prepandClassPath",
    "setting/java/initHeapSize",
    "setting/java/maxHeapSize",
    "setting/java/threadStackSize",
    "ftWeight",
    "shutdown/checkpoint",
    "shutdown/timeout",
]

ordering_list_service = [
    "enabled",
    "bindings",
    "NVPairs",
    "failureCount",
    "failureInterval",
    "bwprocesses",
    "isFt",
    "faultTolerant/hbInterval",
    "faultTolerant/activationInterval",
    "faultTolerant/preparationDelay",
]

# Generate Bindings on Element Tree
def PatchServiceSettings(elem_binding, binding_opts_map, parent_map, ordering_list, xmlns=None, doClear=True ):
    def ordered_compare(x, y):
        x_ind = ordering_list.index(x) if x in ordering_list else -1
        y_ind = ordering_list.index(y) if y in ordering_list else -1

        if x_ind >= 0:
            if y_ind < 0: return -1
            else: return cmp(x_ind, y_ind)
        if y_ind >= 0:
            if x_ind < 0: return 1
            else: return cmp(x_ind, y_ind)

        return cmp(x,y)


    opts_str_list = binding_opts_map.keys()
    opts_str_list.sort(ordered_compare)

    ns = ''
    if xmlns is not None: ns = '{%s}' % xmlns

    # Clear Elements
    if doClear:
        for opt in opts_str_list + ['contact/', 'description/']:
            elem_str = opt.split('/')[0]
            elem_sub = elem_binding.find(ns + elem_str)

            if elem_sub is not None:
                elem_parent = parent_map[elem_sub]
                elem_parent.remove(elem_sub)

    # Add Elements
    for opt in opts_str_list:
        elem = elem_binding
        value = binding_opts_map[opt]
        value_assigned = False

        elem_strs_tmp = opt.split('/')
        elem_strs = []

        for elem_str in elem_strs_tmp:
            if elem_str.find('.') >= 0:
                name, attr = elem_str.split('.')
                if len(name) > 0: elem_strs.append(name)
                if len(attr) > 0: elem_strs.append("." + attr)
            else:
                elem_strs.append(elem_str)

        for elem_str in elem_strs:
            if elem_str is None or len(elem_str) == 0:
                continue
                
            if elem_str[0] == '.':
                elem.attrib[elem_str[1:]] = value
                value_assigned = True
            else:
                sub_elem = elem.find(ns + elem_str)
                if sub_elem is None:
                    sub_elem = ET.SubElement(elem, ns + elem_str)

                elem = sub_elem
        if not value_assigned:
            elem.text = value



def UpdateGlobalVariables(target, local_env=locals(), xmlns="http://www.tibco.com/xmlns/repo/types/2002"):
    options = target_settings.options(target)
    options.sort()

    cwd=os.getcwd()
    options = map(lambda x: 'defaultVars/' + x, options)
    variable_file='defaultVars.substvar'
    
    log.info('')
    log.info('-- Updating global variables of target: ' + target)
    
    try:
        total_changes = 0
        for opt in options:
            os.chdir(cwd)
            
            # exclude Bindings
            if opt.find('Bindings') >= 0 or opt.find('Deployment') >= 0 or opt.find('Service Settings') >= 0:
                continue
                
            for part in opt.split('/')[:-1]:
                os.chdir(part)               
            
            tree = ET.parse('defaultVars.substvar')
            var_name = opt.split('/')[-1]
            key = opt.replace('defaultVars/', '')            
            value = target_settings.get(target, key)

            elem_vars = tree.find("{%s}globalVariables" % xmlns)
               
            nodes = elem_vars.findall("{%s}globalVariable" % xmlns)
            cnt_changes = 0
            for node in nodes:
                if node.find('{%s}name' % xmlns).text == var_name:
                    node_value = node.find('{%s}value' % xmlns)
                    value_orig = node_value.text
                    node_value.text =  value
                    #print int(time.time() * 1000)
                    #node.find('{%s}modTime' % xmlns).text = int(time.time() * 1000)
                    if value_orig != value:
                        log.info("%s has been changed from %s to %s" % (key, value_orig, value))
                        cnt_changes += 1
                    
            if cnt_changes > 0:
                tree.write(variable_file)
                contents = ''
                with file(variable_file) as fp:
                    contents = ''.join(fp.readlines()).replace('ns0:', '').replace(':ns0', '')
                with file(variable_file, 'w+') as fp:
                    fp.write(contents)                
                #log.info('Changes have been applied to the file.')
                total_changes += cnt_changes
                
        if total_changes == 0:
            log.info('No changes.')
    finally:
        os.chdir(cwd)

# Get application configurations.
def GetBindingOptionsMap(target, local_env=locals()):
    ret = GetMappedOptionsMap(target, 'Bindings', local_env)
    return ret

def GetDeploymentOptionsMap(target, local_env=locals()):
    return GetOptionsMap(target, 'Deployment', local_env)

def GetServiceOptionsMap(target, local_env=locals()):
    return GetOptionsMap(target, 'Service Settings', local_env)

def GetOptionsMap(target, section_name, local_env):
    binding_opts_map = {}

    service_opts = target_settings.options(section_name)

    for opt in service_opts:
        binding_opts_map[opt] = target_settings.get(section_name, opt) % local_env

    if target in target_settings.sections():
        for opt in target_settings.options(target):
            if opt.find(section_name) >= 0:
                key = opt[len(section_name)+1:]
                value = target_settings.get(target, opt) % local_env
                binding_opts_map[key] = value
                local_env[key] = value

    return binding_opts_map

def GetMappedOptionsMap(target, section_name, local_env):
    binding_opts_map = {}

    service_opts = target_settings.options(section_name)

    for opt in service_opts:
        binding_name = opt.split('/')[0] % local_env
        service_opt = '/'.join(opt.split('/')[1:])
        if not binding_opts_map.has_key(binding_name):
            binding_opts_map[binding_name] = {}

        binding_opts_map_item = binding_opts_map[binding_name]
        binding_opts_map_item[service_opt] = target_settings.get(section_name, opt) % local_env

    if target in target_settings.sections():
        for opt in target_settings.options(target):
            if opt.find(section_name) >= 0:
                key = opt[len(section_name)+1:]
                value = target_settings.get(target, opt) % local_env
                binding_name = key.split('/')[0] % local_env
                service_opt = '/'.join(key.split('/')[1:])

                if not binding_opts_map.has_key(binding_name):
                    binding_opts_map[binding_name] = {}

                binding_opts_map_item = binding_opts_map[binding_name]
                binding_opts_map_item[service_opt] = value

    return binding_opts_map

def OverrideConfiguration(site, config={}):
    keys = []
    prefix = site + "/"
    for opt in target_settings.options('Configuration'):
    # if option name is started with string: 'Configurtaion/'
        if opt.find(prefix) == 0:
            key = opt.split(prefix)[1]
            val = target_settings.get('Configuration', opt)
            config[key] = val
            keys.append(key)

    return keys

def LoadDeployerConfig(ini_file, argv=sys.argv, config={}, override=False):

    if not override:
        bin_path = os.path.sep.join(argv[0].split(os.path.sep)[:-1])
        default_ini_file_path = os.path.sep.join([bin_path, ini_file])
        config['target_file_path'] = target_config_file_name
    else:
        default_ini_file_path = ini_file

    try:
        ini_file_path = default_ini_file_path

        # If setting file is exsited in working dir, use it
        if os.path.exists(ini_file):
            ini_file_path = ini_file

        if not os.path.exists(ini_file_path):
            raise IOError

        settings = CaseSensitiveConfigParser()
        settings.read(ini_file_path)

    except IOError:
      print('Fatal Error: Cannot Find %s' % ini_file)
      sys.exit(1)

    if not override:
        for key in ['tra_bin', 'logfile', 'buildear', 'appmanage', 'ear_build_dir',
            'config_export_dir']:

            config[key] = settings.get('Configuration', key)

    # optional

    for key in ['ear_file', 'project_name', 'config_file', 'remote_host', 'remote_dir', 'remote_tra_bin', 'admin_user',
        'admin_pass', 'domain']:
        try:
            config[key] = settings.get('Configuration', key)
        except:
            pass

    return config


if __name__ == '__main__':

    cmd_list = sys.argv[1:]
    # parsing options
    opts, args = ([], [])

    TASK_EAR = 'ear'
    TASK_CONFIG = 'config'
    TASK_DEPLOY  = 'deploy'
    TASK_UPLOAD  = 'upload'
    TASK_UPDATE_VAR = 'updatevar'
    TASK_ALL     = 'build_all'
    task_list = [TASK_ALL, TASK_EAR, TASK_CONFIG, TASK_DEPLOY, TASK_UPLOAD, TASK_UPDATE_VAR]
    
    target_name = None
    task = [task_list[0]]
    remote_deploy = False
    deploy_desc = ''
    
    usage = """
               [ BusinessWorks deploy automation script. ]
                written by yongki82.kim@samsung.com, 2011
    
    [usage] 
            ./deployer [task, [task, [...]]] -t target_name [-r]
            
    [options]
            -d, --desc=               : specify descriptions for deploy objectives.
            -f, --config-file=        : specify deployer configuration file
                                        (defalut: deployer.ini)
            -c, --target-config-file= : specify target configuration file 
                                        (defalut: targets.ini)
            -t, --target=             : targetname to build in [Targets] 
                                        section on targets.ini
            -r, --remote-deploy       : commit deployment remotely.
            
    [notice] - task must be one of [%s].
             - default task is : %s
           
    [example] ./ deployer config deploy --target=test
               # make deploy and config on targets dev and test.
    """ % (",".join(task_list[1:]), task_list[0])
    
    try:
        opts, args = getopt.gnu_getopt(cmd_list, "t:f:c:d:r", ["target=", "desc=", "config-file=", "target-config-file=", "remote-deploy"])
    except getopt.GetoptError, err:
        if getopt.GetoptError.opt in ['h']:
            print usage + "Error: %s\n" % str(err)
            sys.exit(1)

    for o, a in opts:
        if o in ("-t", "--target"):
            target_name = a
        elif o in ("-d", "--desc"):
            deploy_desc = a
        elif o in ("-f", "--config-file"):
            config_file_name = a
        elif o in ("-c", "--target-config-file"):
            target_config_file_name = a
        elif o in ("-r", "--remote-deploy"):
            remote_deploy = True
        else:
            print "Error: not supported option %s.\n" % o
            sys.exit(1)

    if target_name == None:
      print usage
      print "    Error! No target is specified. please make sure the target to be built."
      print 
      sys.exit(1)


    deployer_path = os.path.join(os.path.expandvars('$HOME'), '.deployer', config_file_name)
    deployer_path_win = os.path.join(os.path.expandvars('$APPDATA'), '.deployer', config_file_name)
    if (os.path.exists(deployer_path)):
        config = LoadDeployerConfig(deployer_path)
    elif (os.path.exists(deployer_path_win)):
        config = LoadDeployerConfig(deployer_path_win)
    else:
        config = LoadDeployerConfig(config_file_name)


    target_file_path = config['target_file_path']

    try:
        # Initiailize logging class.
        log = logging.getLogger('deployer')
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        log_handlers = [logging.FileHandler(config['logfile']), logging.StreamHandler()]

        for handler in log_handlers:
            handler.setFormatter(formatter)
            log.addHandler(handler)
        log.setLevel(logging.INFO)

        for t in args:
            if t not in task_list:
                log.error('Invalid task: ' + t)
            task.append(t)

        if len(task) > 1:
            task = task[1:]

        log.info('BusinessWorks Deploy Automator is now starting...\n')

        try:
            if os.path.exists(target_file_path):
                target_settings = CaseSensitiveConfigParser()
                target_settings.read(target_file_path)
                if 'Configuration' in target_settings.sections():
                    log.info("Overriding Configurations...")
                    LoadDeployerConfig(target_file_path, config=config, override=True)
            else:
              raise IOError
        except IOError:
          log.error('Cannot Find %s' % target_file_path)
          sys.exit(1)

        # Get Target Lists
        try:
            targets = []
            for target in target_name.split(','):
                targets = targets + GetTargets(target_settings, target, log)
        except:
            targets = target_name.split(',')

        t1 = time.time()
        today = time.strftime('%Y%m%d')

        target                      = ''
        project_dir   = config['project_dir']  = os.getcwd()
        version       = config['version'] = target_settings.get('Default', 'version') % locals()

        appname_tmp    = target_settings.get('Default', 'appname')
        appname       = appname_tmp % locals()

        if not config.has_key('prject_name'):
            project_name  = config['project_name'] = os.path.split(project_dir)[-1]
        else:
            project_name  = config['project_name'] 
        ear_file      = config['ear_file']     = appname_tmp + '.ear'
        config_file   = config['config_file']  = appname_tmp + '.xml'
        config['target'] = target_name
            
        package_file_tmp = config['package_file_tmp'] = appname_tmp % config + '_%(build_date)s.tar'
        ear_build_dir     = config['ear_build_dir']
        config_export_dir = config['config_export_dir']
        log.info('Target: ' + str(targets))


        if not os.path.exists(ear_build_dir):
            os.mkdir(ear_build_dir)

        ear_build_path = config['ear_build_path'] = os.path.sep.join([project_dir, ear_build_dir])
        batch_file_path = config['batch_file_path'] = os.path.sep.join([project_dir, ear_build_dir, 'AppManage.batch'])

        deploy_opts_map       = GetDeploymentOptionsMap(target)
        archive_file_tmp      = deploy_opts_map['archiveFileName']
        ear_file_path_tmp     = os.path.sep.join([project_dir, ear_build_dir, ear_file])
        config_file_path_tmp = os.path.sep.join([project_dir, config_export_dir, config_file])

        build_date = datetime.now().strftime('%Y%m%d_%H%M')

        log.info('build_date        : ' + build_date)
        log.info('project dir       : ' + project_dir)
        log.info('project name      : ' + project_name)
        log.info('project version   : ' + version)
        log.info('archive file name : ' + archive_file_tmp)
        log.info('ear file path     : ' + ear_file)
        log.info('config file path  : ' + config_file)
        log.info('remote deploy mode: ' + str(remote_deploy))

        time.strftime('%Y')

        # some modification on archive file
        GenerateBatchScript(batch_file_path, targets)

        def print_config(site, keys, config):
            log.info("")
            log.info("Target configurations are overridden: " + site)
            for key in keys:
                log.info(" - %-15.15s : %s" % (key, config[key]))

        if len(set([TASK_UPDATE_VAR]).intersection(task)) > 0:
            # Get Target Lists
            try:
                targets = []
                for target in target_name.split(','):
                    targets = targets + GetTargets(target_settings, target, log)
            except:
                targets = target_name.split(',')

            for target in targets:
                # if 'TASK_EAR' is specified, updating variable will be proceeded during TASK_EAR job.
                if len(set([TASK_EAR, TASK_ALL]).intersection(task)) <= 0:
                    UpdateGlobalVariables(target)
            
        else:
            if len(set([TASK_EAR, TASK_ALL]).intersection(task)) > 0:

                for target in targets:
                    deploy_opts_map = GetDeploymentOptionsMap(target)

                    if '.archiveFileName' in target_settings.options(target):
                        archive_file_tmp_user = target_settings.get(target, '.archiveFileName')
                        log.info("archiveFileName detected, override archive file setting to '%s'" % archive_file_tmp_user)
                        archive_file_tmp_final = archive_file_tmp_user.replace("%%", "%")
                    else:
                        archive_file_tmp_final = archive_file_tmp

                    tree = ET.parse(archive_file_tmp_final % locals())

                    archive_file_out = archive_file = archive_file_tmp_final % locals()
                    ear_file_path = ear_file_path_tmp % locals()

                    if '.targetFileNameTo' in target_settings.options(target):
                        target_file_name = target_settings.get(target, '.targetFileNameTo') % locals()
                        archive_file_out = target_file_name + '.archive'
                        ear_file_path = ear_file_path.replace(appname_tmp % locals(), target_file_name)
     
                    # Generate temporary archive file
                    log.info('-- Generating temporary archive files for %(target)s' % locals())

                    elem_ear = tree.find('enterpriseArchive')
                    elem_ear.find('versionProperty').text = version
                    elem_ear.find('authorProperty').text  = target_settings.get('Default', 'author')
                    elem_ear.find('name').text            = appname_tmp % locals()
                    elem_ear.find('fileLocationProperty').text  = ear_file_path

                    elem_sar = elem_ear.find('sharedArchive')
                    elem_sar.find('authorProperty').text  = target_settings.get('Default', 'author')

                    elem_par = elem_ear.find('processArchive')
                    elem_par.attrib['name'] = appname_tmp % locals()
                    elem_par.find('authorProperty').text  = target_settings.get('Default', 'author')

                    if archive_file_out.find(target) < 0: archive_file_out = archive_file.replace('.archive', '%s.archive' % target)
                    tree.write(os.path.sep.join([ear_build_dir, archive_file_out]) )

                for target in targets:
                    os.chdir(config['project_dir'])
                    UpdateGlobalVariables(target)
                    # build .ear file
                    ear_file_path = ear_file_path_tmp % locals()
                    archive_file_out = archive_file = archive_file_tmp_final % locals()
                    if archive_file_out.find(target) < 0: archive_file_out = archive_file.replace('.archive', '%s.archive' % target)
                    os.chdir(config['tra_bin'])

                    try:
                        os.remove(ear_file_path)
                    except:
                        pass

                    log.info('')
                    log.info('-- Launch buildear to building enterprise archive')
                    args = ['-ear', '/' + ear_build_dir + '/' + archive_file_out, '-o', ear_file_path, '-p', project_dir]
                    p = sysif.subproc.launchWithoutConsole(config['buildear'], args)

                    prog = re.compile('.*Are you sure*')
                    filter_progs = [
                        re.compile('Exception in DesignerResource.*'),
                        re.compile('.*using unknown file type resource.*'),
                        re.compile('.*Are you sure*'),
                        re.compile('^\s*$')
                    ]
                    ret = sysif.subproc.recv_some_restring(p, prog, t=100, tr=100, e=0, filter_progs=filter_progs, verbose=log.info)

                    if ret.find('has built correctly') < 0:
                        sysif.subproc.send_all(p, 'y\r\n')

                    p.wait()

                    # Export Configuration File using AppManage]
                    config_file_path = config_file_path_tmp % locals()

                    if '.targetFileNameTo' in target_settings.options(target):
                        target_file_name = target_settings.get(target, '.targetFileNameTo') % locals()
                        config_file_path = config_file_path.replace(appname_tmp % locals(), target_file_name)

                    log.info('')
                    log.info('-- Export configuration of %(ear_file_path)s ...' % locals())
                    args= ['-export', '-ear', ear_file_path, '-out', config_file_path]

                    p = sysif.subproc.launchWithoutConsole(config['appmanage'], args)
                    ret = sysif.subproc.recv_some_restring(p, prog, t=100, tr=100, e=0, verbose=log.info)
                    p.wait()

                    HackVersionConstraint(ear_file_path)

            if len(set([TASK_CONFIG, TASK_DEPLOY, TASK_ALL]).intersection(task)) > 0:
                for target in targets:
                    # Patch global variables on configuration file
                    config_file_path = config_file_path_tmp % locals()

                    if '.targetFileNameTo' in target_settings.options(target):
                        target_file_name = target_settings.get(target, '.targetFileNameTo') % locals()
                        config_file_path = config_file_path.replace(appname_tmp % locals(), target_file_name)

                    print config_file_path
                    options = target_settings.options(target)
                    tree = ET.parse(config_file_path)
                    xmlns = "http://www.tibco.com/xmlns/ApplicationManagement"
                    """
                    nodes = tree.findall("{%s}NVPairs" % xmlns)
                    log.info('-- Patch global variables on %(config_file_path)s' % locals())

                    for node in nodes:
                        for entry in node.findall('{%s}NameValuePair' % xmlns):
                            entry_name  = entry.find('{%s}name' % xmlns)
                            entry_value = entry.find('{%s}value' % xmlns)
                            if entry_name.text in options:
                                value = target_settings.get(target, entry_name.text)
                                entry_value.text = value
                                log.info('%s: %s' % (entry_name.text, value))
                    """
                    # TODO : to enable FT configuration, binding should be able to be multiple.
                    appname = appname_tmp % locals()

                    # Find the first-matched node of 'binding'
                    log.info('-- Generating service settings')
                    binding_opts_map = GetBindingOptionsMap(target)

                    # Get binding names and remove a name of 'default' from the list.
                    bindings = binding_opts_map.keys()
                    bindings.pop(bindings.index('default'))
                    bindings.sort()
                    parent_map = dict((c, p) for p in tree.getiterator() for c in p)

                    # Patch repository type as local
                    repoinst = tree.find('.//{%s}repoInstances' % xmlns)
                    repoinst.attrib['selected'] = 'local'

                    for binding in bindings:
                        elem_binding = tree.find('.//{%s}binding' % xmlns)
                        elem_parent = parent_map[elem_binding]

                        # If the number of bindings is multiple, append another binding node.
                        if bindings.index(binding) > 0:
                            newtree = ET.parse(config_file_path)
                            elem_binding = newtree.find('.//{%s}binding' % xmlns)
                            elem_parent.append(elem_binding)
                            parent_map = dict((c, p) for p in tree.getiterator() for c in p)

                        # override default binding options with specified binding options.
                        binding_opt = copy.copy(binding_opts_map['default'])

                        # set binding name
                        binding_opt['.name'] = binding

                        for key in binding_opts_map[binding].keys():
                            binding_opt[key] = binding_opts_map[binding][key]

                        PatchServiceSettings(elem_binding, binding_opt, parent_map, ordering_list_binding, xmlns=xmlns, doClear=True)

                    # Patch Service Settings
                    elem_bw = tree.find('.//{%s}bw' % xmlns)
                    service_opt = GetServiceOptionsMap(target)
                    service_opt['.name'] = appname + '.par'

                    PatchServiceSettings(elem_bw, service_opt, parent_map, ordering_list_service, xmlns)
                        
                    # Write Deploy Configuration

                    IndentElem(tree.getroot())

                    tree.write(config_file_path)
                    contents = ''
                    with file(config_file_path) as fp:
                        contents = ''.join(fp.readlines()).replace('ns0:', '').replace(':ns0', '')

                    with file(config_file_path, 'w+') as fp:
                        fp.write(contents)

            if len(set([TASK_DEPLOY, TASK_ALL]).intersection(task)) > 0:
               
                site_target_map = {'default':[]}
                log.info('')
                log.info('-- Deployment process is started...')
                log.info('')

                for target in targets:
                    if '.site' in target_settings.options(target):
                        site = target_settings.get(target, '.site')
                        if site_target_map.has_key(site):
                            site_target_map[site].append(target)
                        else:
                            site_target_map[site] = [target]
                    else:
                        site_target_map['default'].append(target)
                    
                for site in site_target_map.keys():

                    targets = site_target_map[site]

                    if targets == []: continue

                    target_config = copy.copy(config)

                    package_files = glob.glob( ear_build_path + "/*%s*.tar" % target)
                    package_files.sort()
                    target_config['package_file'] = package_file_tmp % locals()

                    if len(deploy_desc) > 0:
                        deploy_desc = '_' + target_name + '_' + deploy_desc.replace(' ', '_')
                    else:
                        deploy_desc = '_' + target_name

                    target_config['deploy_desc']  = deploy_desc
                    target_config['package_file'] = package_file_tmp % locals()
                    
                    if len(set([TASK_DEPLOY]).intersection(task)) > 0 and \
                       len(package_files) > 0:
                        log.info( "Package already exists: use last-created package" )
                        package_file_path = package_files[-1]
                        build_date = package_file_path[-17:-4]
                        log.info("Build date: " + build_date)
                        log.info( "Package file: " + target_config['package_file'] )
                        target_config['build_date'] = build_date
                        keys = OverrideConfiguration(site, target_config)
                    else:
                        target_config['build_date'] = build_date
                        keys = OverrideConfiguration(site, target_config)
                        package_file_path_tmp   = os.path.sep.join([project_dir, ear_build_dir, package_file_tmp])
                        package_file_path = config['package_file_path'] = package_file_path_tmp % locals()
                        print_config(site, keys, target_config)

                        log.info('-- Generating Batch Script for: ' + site)
                        GenerateBatchScript(batch_file_path, targets)

                        log.info('-- Packaging Deployed Files: ' + package_file_path)
                        PackDeployFiles(package_file_path, build_date, targets, ear_build_path, target_config, deploy_desc)

                    log.info('-- Upload Packaged File')

                    if target_config.has_key('proxy_hosts'):
                        hosts = target_config['proxy_hosts'].split(",")

                        sysif.net.rftp('-uv @' + hosts[0] + ' -b%(ear_build_dir)s -l%(ear_build_path)s %(package_file)s' % target_config, verbose_func=log.info)
                        sysif.net.rcmd('@'+hosts[0]+' rftp -uv @'+hosts[1]+' -b%(ear_build_dir)s -l%(ear_build_dir)s %(package_file)s' % target_config, verbose_func=log.info, timeout=30)
                        sysif.net.rcmd('@'+hosts[0]+' rcmd @'+hosts[1]+' rftp -uv @%(remote_host)s -b%(remote_dir)s -l%(ear_build_dir)s %(package_file)s' % target_config, verbose_func=log.info, timeout=30)
                        ret = sysif.net.rcmd('-v @'+hosts[0]+' rcmd @'+hosts[1]+' rcmd @%(remote_host)s -b%(remote_dir)s tar xvf %(package_file)s' % target_config, verbose_func=log.info, timeout=30)
                        if ret.find("deploy.sh") < 0:
                            print "try again..."
                            ret = sysif.net.rcmd('-v @'+hosts[0]+' rcmd @'+hosts[1]+' rcmd @%(remote_host)s -b%(remote_dir)s tar xvf %(package_file)s' % target_config, verbose_func=log.info, timeout=300)

                        if remote_deploy == True:
                            log.info('Starting remote deploy for SAS...')
                            ret = sysif.net.rcmd('-v @'+hosts[0]+' rcmd @'+hosts[1]+' rcmd @%(remote_host)s -b%(remote_dir)s/%(build_date)s sh deploy.sh' % target_config, verbose_func=log.info, timeout=300)
                            if ret.find("Finished") < 0:
                                print "try again..."
                                ret = sysif.net.rcmd('-v @'+hosts[0]+' rcmd @'+hosts[1]+' rcmd @%(remote_host)s -b%(remote_dir)s/%(build_date)s sh deploy.sh' % target_config, verbose_func=log.info, timeout=30)
                    else:
                        sysif.net.rftp('-uv @%(remote_host)s -b%(remote_dir)s -l%(ear_build_path)s %(package_file)s' % target_config, verbose_func=log.info)
                        log.info('-v @%(remote_host)s -b%(remote_dir)s tar xf %(package_file)s' % target_config)
                        sysif.net.rcmd('-v @%(remote_host)s -b%(remote_dir)s tar xf %(package_file)s' % target_config, verbose_func=log.info)
                        log.info("extract files completed...")

                        if remote_deploy == True:
                            log.info('Starting remote deploy...')
                            sysif.net.rcmd('-v @%(remote_host)s -b%(remote_dir)s/%(build_date)s sh deploy.sh' % target_config, verbose_func=log.info)

        log.info('%.3f seconds elapsed' % (time.time() - t1) )
        log.info('All processses are completed successfully..')
        log.info('Done')
    finally:
        for handler in log_handlers:
            log.removeHandler(handler)
