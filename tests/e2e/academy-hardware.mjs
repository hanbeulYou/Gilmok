import console from "node:console";

import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
// Read only. Never change the user's power or display settings.
const battery=execFileSync('pmset',['-g','batt'],{encoding:'utf8'});
const hardware=execFileSync('system_profiler',['SPHardwareDataType'],{encoding:'utf8'});
const display=execFileSync('swift',['-e',`import Cocoa
import CoreGraphics
import Foundation
print("lowPower", ProcessInfo.processInfo.isLowPowerModeEnabled)
for screen in NSScreen.screens {
let id=(screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! NSNumber).uint32Value
print(screen.localizedName, CGDisplayCopyDisplayMode(id)!.refreshRate, screen.frame, screen.backingScaleFactor)
}`],{encoding:'utf8'});
const valid=battery.includes('AC Power')&&hardware.includes('Apple M5 Pro')&&display.includes('lowPower false')&&display.trim().split('\n').slice(1).every(line => /\b60\.0\b/.test(line));
const proof={at:new Date().toISOString(),battery,chip:hardware.match(/Chip:\s*(.*)/)?.[1],display,valid};
mkdirSync('.local/academy-b',{recursive:true});writeFileSync('.local/academy-b/hardware.json',JSON.stringify(proof,null,2));
console.log(JSON.stringify(proof,null,2));
if(!valid)throw new Error('FPS requires M5 Pro, AC, 60Hz, low power off; ask user to configure.');
