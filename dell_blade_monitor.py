#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import paramiko
import argparse
try:
    import protobix3 as protobix
except:
    import protobix

PBX_SERVER = '127.0.0.1'
PBX_PORT = '10051'

PWR_STATE = {
    "N/A":     0,
    "OFF":     1,
    "OFFLINE": 2,
    "ON":      3,
    "ONLINE":  4,
    "STANDBY": 5,
    "PRIMARY": 6
}

HEALTH_STATE = {
    "N/A":     0,
    "FAILED":  1,
    "NOT OK":  2,
    "WARNING": 3,
    "OK":      4
}

class SSH:
    def __init__(self, **kwargs):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.kwargs = kwargs
  
    def __enter__(self):
        kw = self.kwargs
        self.client.connect(hostname=kw.get('hostname'), username=kw.get('username'),
                            password=kw.get('password'), port=int(kw.get('port', 22)))
        return self
  
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
  
    def exec_cmd(self, cmd):
        stdin, stdout, stderr = self.client.exec_command(cmd)
        data, error= stdout.read(), stderr.read()
        if error:
            raise ValueError(error.decode())
        return data.decode()

def format_errors(errorString):
    strings = errorString.split('\n')
    errorData = []
    errorTotalDict = {}
    for i in range(len(strings)):
        if (i+1) % 4:
            if strings[i]:
                stringParsed = strings[i].split('=')
                errorData.append(stringParsed[1].strip())
            else:
                continue
        else:
            moduleName = errorData[0].upper()
            if errorTotalDict.get(moduleName):
                errorTotalDict[moduleName].append({'severity': errorData[1], 'message': errorData[2]})
            else:
                errorTotalDict[moduleName] = [{'severity': errorData[1], 'message': errorData[2]}]
            errorData = []
    return errorTotalDict

def data_send(data_to_send, pbx_server, pbx_port):
    zbx_datacontainer = protobix.DataContainer()
    zbx_datacontainer.server_active = pbx_server
    zbx_datacontainer.server_port = int(pbx_port)
    zbx_datacontainer.data_type = 'items'
    zbx_datacontainer.add(data_to_send)
    zbx_datacontainer.send()

def parse_argse():
    parser = argparse.ArgumentParser()
    parser.add_argument('--zhost', help='Zabbix host for protobix module', required=True)
    parser.add_argument('--host', help='Dell chassis address', required=True)
    parser.add_argument('--user', help='Dell chassis login', required=True)
    parser.add_argument('--passwd', help='Dell chassis passwd', required=True)
    parser.add_argument('--mode', help='discover or check', required=True)
    parser.add_argument('--port', help='Dell chassis port', default=22)
    return parser.parse_args()

def discover(ssh):
    lldArray = []
    dellAnswerArray = ssh.exec_cmd('getmodinfo').split('\n')
    for dellAnswer in dellAnswerArray:
        if dellAnswer:
            moduleName = dellAnswer.split()[0]
            lldArray.append({'{#DELL.MODULE.NAME}' : moduleName})
    data = {'data':lldArray}
    return data

def check(ssh):
    data = {}
    errorsDict = {}
    dellModuleArray = ssh.exec_cmd('getmodinfo').split('\n')
    dellErrors = ssh.exec_cmd('getactiveerrors')
    if dellErrors:
        try:
            errorsDict = format_errors(dellErrors)
        except:
            pass
    moduleNameIndex, presenceIndex, powerStateIndex, healthIndex, serviceTagIndex = dellModuleArray[0].find('<module>'), dellModuleArray[0].find('<presence>'),\
         dellModuleArray[0].find('<pwrState>'), dellModuleArray[0].find('<health>'), dellModuleArray[0].find('<svcTag>')
    dellModuleArray.pop(0)
    for dellAnswer in dellModuleArray:
        critacalErros = []
        nonCriticalErrors = []
        if dellAnswer:
            moduleName, presence, pwrState, health = dellAnswer[moduleNameIndex:presenceIndex].strip(), dellAnswer[presenceIndex:powerStateIndex].strip(),\
                dellAnswer[powerStateIndex:healthIndex].strip(), dellAnswer[healthIndex:serviceTagIndex].strip()
            presence = 1 if presence == 'Present' else 0
            pwrState = PWR_STATE.get(pwrState.upper(), 0)
            health = HEALTH_STATE.get(health.upper(), 0)
            for error in errorsDict.get(moduleName.upper(), []):
                if error.get('severity') == 'Critical':
                    critacalErros.append(error.get('message'))
                elif error.get('severity') == 'NonCritical':
                    nonCriticalErrors.append(error.get('message'))
            data.update({
                'presence[{}]'.format(moduleName) : presence,
                'power[{}]'.format(moduleName) : pwrState,
                'health[{}]'.format(moduleName) : health,
                'critical[{}]'.format(moduleName) : '\n'.join(critacalErros),
                'noncritical[{}]'.format(moduleName) : '\n'.join(nonCriticalErrors)
                })
    return data

def main():
    args = parse_argse()
    lldResult = []
    result = {}
    errors = []
    try:
        with SSH(hostname=args.host, username=args.user, password=args.passwd, port=args.port) as ssh:
            if args.mode == 'discover':
                try:
                    lldResult = discover(ssh)
                except Exception as e:
                    errors.append('Во время получения данных для автообнаружения возникли ошибки. Подробное описание проблемы:\n{}'.format(e))                
                print(json.dumps(lldResult, indent=4))
            elif args.mode == 'check':
                try:
                    result = check(ssh)
                except Exception as e:
                    errors.append('Во время получения данных возникли ошибки. Подробное описание проблемы:\n{}'.format(e))
    except Exception as e:
        errors.append('Во время подключения к хосту для получения данных возникли ошибки. Подробное описание проблемы:\n{}'.format(e))
    result.update({'dell_script_errors': '\n'.join(errors)})
    result = {args.zhost : result}
    data_send(result, PBX_SERVER, PBX_PORT)

if __name__ == "__main__":
    main()