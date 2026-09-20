using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;

class DumpManagedIl {
  static readonly Dictionary<ushort,OpCode> Ops = new Dictionary<ushort,OpCode>();
  static DumpManagedIl() { foreach(var f in typeof(OpCodes).GetFields(BindingFlags.Public|BindingFlags.Static)) { var o=(OpCode)f.GetValue(null); Ops[unchecked((ushort)o.Value)]=o; } }
  static int I4(byte[] b, ref int p) { int v=BitConverter.ToInt32(b,p); p+=4; return v; }
  static void Main(string[] a) {
    if(a.Length<3) throw new ArgumentException("assembly type method");
    AppDomain.CurrentDomain.AssemblyResolve += (s,e) => { try { return Assembly.LoadFrom(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(a[0]),new AssemblyName(e.Name).Name+".dll")); } catch { return null; } };
    var asm=Assembly.LoadFrom(a[0]); var t=asm.GetType(a[1],true);
    foreach(var m in t.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Static|BindingFlags.Instance|BindingFlags.DeclaredOnly)) {
      if(m.Name.IndexOf(a[2],StringComparison.OrdinalIgnoreCase)<0) continue;
      Console.WriteLine("METHOD "+m);
      var body=m.GetMethodBody(); if(body==null) continue; var b=body.GetILAsByteArray(); int p=0;
      while(p<b.Length) { int at=p; ushort k=b[p++]; if(k==0xfe) k=(ushort)(0xfe00|b[p++]); OpCode op; if(!Ops.TryGetValue(k,out op)) throw new Exception("opcode"); object val=null;
        switch(op.OperandType) {
          case OperandType.ShortInlineI: val=(sbyte)b[p++]; break;
          case OperandType.InlineI: val=I4(b,ref p); break;
          case OperandType.InlineI8: val=BitConverter.ToInt64(b,p);p+=8;break;
          case OperandType.ShortInlineR: val=BitConverter.ToSingle(b,p);p+=4;break;
          case OperandType.InlineR: val=BitConverter.ToDouble(b,p);p+=8;break;
          case OperandType.ShortInlineBrTarget: val=(p+1+(sbyte)b[p]);p++;break;
          case OperandType.InlineBrTarget: {int d=I4(b,ref p);val=p+d;break;}
          case OperandType.ShortInlineVar: val=b[p++];break;
          case OperandType.InlineVar: val=BitConverter.ToUInt16(b,p);p+=2;break;
          case OperandType.InlineString: {int z=I4(b,ref p);try{val="\""+asm.ManifestModule.ResolveString(z)+"\"";}catch{val="token 0x"+z.ToString("x8");}break;}
          case OperandType.InlineField: case OperandType.InlineMethod: case OperandType.InlineType: case OperandType.InlineTok: case OperandType.InlineSig: {int z=I4(b,ref p);try{val=asm.ManifestModule.ResolveMember(z).ToString();}catch{val="token 0x"+z.ToString("x8");}break;}
          case OperandType.InlineSwitch: {int n=I4(b,ref p);p+=4*n;val=n+" targets";break;}
        }
        Console.WriteLine("{0:x4}: {1,-14} {2}",at,op.Name,val);
      }
    }
  }
}
