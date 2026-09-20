param([string]$Assembly,[string]$Type,[string]$Method)
$ErrorActionPreference='Stop'
[Reflection.Assembly]::LoadFrom((Join-Path (Split-Path $Assembly) 'LibUsbDotNet.LibUsbDotNet.dll'))|Out-Null
$a=[Reflection.Assembly]::LoadFrom($Assembly);$t=$a.GetType($Type,$true)
$ops=@{};[Reflection.Emit.OpCodes].GetFields([Reflection.BindingFlags]'Public,Static')|%{$o=$_.GetValue($null);$ops[([int]$o.Value-band 0xffff)]=$o}
foreach($m in $t.GetMethods([Reflection.BindingFlags]'Public,NonPublic,Static,Instance,DeclaredOnly')|? Name -like "*$Method*"){
  "METHOD $m";$b=$m.GetMethodBody().GetILAsByteArray();$p=0
  while($p-lt$b.Length){$at=$p;$k=[int]$b[$p++];if($k-eq0xfe){$k=[int](0xfe00-bor$b[$p++])};$o=$ops[$k];if($null-eq$o){throw "unknown opcode $k at $at"};$v=''
    switch($o.OperandType.ToString()){
      ShortInlineI {$v=[int]$b[$p];if($v-gt127){$v-=256};$p++}
      InlineI {$v=[BitConverter]::ToInt32($b,$p);$p+=4}
      InlineI8 {$v=[BitConverter]::ToInt64($b,$p);$p+=8}
      ShortInlineR {$v=[BitConverter]::ToSingle($b,$p);$p+=4}
      InlineR {$v=[BitConverter]::ToDouble($b,$p);$p+=8}
      ShortInlineBrTarget {$d=[int]$b[$p];if($d-gt127){$d-=256};$v=$p+1+$d;$p++}
      InlineBrTarget {$d=[BitConverter]::ToInt32($b,$p);$p+=4;$v=$p+$d}
      ShortInlineVar {$v=$b[$p++]}
      InlineVar {$v=[BitConverter]::ToUInt16($b,$p);$p+=2}
      InlineString {$z=[BitConverter]::ToInt32($b,$p);$p+=4;try{$v='"'+$a.ManifestModule.ResolveString($z)+'"'}catch{$v=('token 0x{0:x8}'-f$z)}}
      {$_-in'InlineField','InlineMethod','InlineType','InlineTok','InlineSig'} {$z=[BitConverter]::ToInt32($b,$p);$p+=4;try{$v=$a.ManifestModule.ResolveMember($z).ToString()}catch{$v=('token 0x{0:x8}'-f$z)}}
      InlineSwitch {$n=[BitConverter]::ToInt32($b,$p);$p+=4+4*$n;$v="$n targets"}
    }
    '{0:x4}: {1,-14} {2}'-f$at,$o.Name,$v
  }
}
