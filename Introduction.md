# Motivation and Implementation of automation script for BW projects.

# Introduction #

## Motivation ##

BW is fantastic tool for creating EAI application for integration multiple data sources such as DB, FTP, or HTTP. However **one serious problem** is block us to get to the Developer's Heaven.

  * Shared resource cannot be dynamically overriden.
    * We have to **_duplicate_** same multiple processes with different resource name such as '.sharedjdbc'.
  * _Yeah_, we can choose another strategy -- seperate shared resource's with global variable:
    * But if we have to support multiple sites?
    * Only manual way supported: if we have 10 different DB with same EAI logic, we have to change **corresponding DB or FTP connection name 10 times** everytime we want to deploy new changes.
  * Why do we have to always manage server-side configuration at the TIBCO administrator?
    * Thread count, heap min&max size, stack sizes...
    * Target host at the domain
  * Can't we automate all the messy things with web-browser with decent command line tool?


## Implementation ##

  * Manage project with centralized configuration file similiar with  Makefile or ant's 'build.xml'
  * Hack archive configuration(.xml) file which 'buildear' script creates with our configuration file(.ini)
  * Update all the global variables in the archive configuration with our target on the configuration file.
  * Again, build .ear file with 'buildear' script. And pack all the things with one simple 'deploy.sh' script which ultimate call 'AppManage' script of the domain administration server.
  * Remotely run the 'deploy.sh'

## Sample configuration File ##
  * https://code.google.com/p/tibco-bw-deployer/source/browse/targets.sample.ini

```
[Configuration]

REMOTELINE/remote_host=remotehost1
REMOTELINE/remote_dir=/users/rbwadmin/deploy
REMOTELINE/remote_tra_bin=/users/rbwadmin/tibco/tra/5.5/bin
REMOTELINE/admin_user=admin
REMOTELINE/admin_pass=admin1
REMOTELINE/domain=MY_DOMAIN3
REMOTELINE/proxy_hosts=proxy1,proxy2

remote_host=server1
remote_dir=/users/bwadmin/deploy
remote_tra_bin=/users/bwadmin/tibco/tra/5.7/bin

admin_user=admin
admin_pass=Ekfrl2005
domain=PFM_EAI

[Default]
version=1
author=admin@admin.com
appname=SampleProject%(target)s
deployname=PFM/RvSettings/%(appname)s

[Deployment]
archiveFileName=%(project_name)s.archive

[Bindings]
default/product/type=BW
default/product/version=5.9
default/product/location=/users/bwadmin/tibco/bw/5.9

default/setting/startOnBoot=false
default/setting/enableVerbose=false
default/setting/maxLogFileSize=20000
default/setting/maxLogFileCount=5
default/setting/threadCount=1
default/setting/java/initHeapSize=64
default/setting/java/maxHeapSize=256
default/setting/java/threadStackSize=280
default/shutdown/checkpoint=false
default/shutdown/timeout=0

[Service Settings]

[Targets]
Primary=1-1 2-1 3-1 4-1 5-1 5-1
Secondary=1-2 2-2 3-2 4-2 5-2 5-2
All=1-1 2-1 3-1 4-1 5-1 5-1 1-2 2-2 3-2 4-2 5-2 5-2 
OnlyOddsPrimary=1 3 5
OnlyEvensPrimary=2 4
1=1-1 1-2
2=2-1 2-2

[1-1]
Bindings/%(appname)s/machine=server1
RvSettings/Logger/LogDir=/users/bwadmin/log/11/

RvSettings/Process/Service=7500
RvSettings/Process/CMQName=CMQNAMEPROD

...

; REMOTE LINE SAMPLE
[R-1]
; If site is set by '.site' attributes, its configuration would be 
; overriden by the option '.site/*' on [Configuration] section.
.site=REMOTELINE

Bindings/%(appname)s/machine=remotehost1
Bindings/%(appname)s/product/type=BW
Bindings/%(appname)s/product/version=5.3
Bindings/%(appname)s/product/location=/users/rbwadmin/tibco/bw/5.3

;; TEST LINE SAMPLE
[T-1]
Bindings/%(appname)s/machine=testserver1
RvSettings/Logger/LogDir=/users/bwadmin/log/t2/

RvSettings/Process/Service=7500
RvSettings/Process/CMQName=CMQNAMETEST


RvSettings/Logger/LogDir=/users/rbwadmin/log/r2/
RvSettings/Process/Service=7500

RvSettings/Process/CMQName=CMQNAMEPRODREMOTELINE

```