// Interactive per-user native clipboard endpoint. No payload logging or disk storage.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

public static class HapaxClipboard {
    const int MaxText = 1048576, MaxRequest = 1500000, MaxReply = 8192;
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = MaxRequest };
    [DllImport("user32.dll")] static extern bool OpenClipboard(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool CloseClipboard();
    [DllImport("user32.dll")] static extern bool EmptyClipboard();
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowEx(uint ex, string cls, string name, uint style, int x, int y, int w, int h, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")] static extern uint GetClipboardSequenceNumber();
    [DllImport("user32.dll")] static extern IntPtr SetClipboardData(uint format, IntPtr data);
    [DllImport("user32.dll")] static extern IntPtr GetClipboardData(uint format);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern uint RegisterClipboardFormat(string name);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalAlloc(uint flags, UIntPtr bytes);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalLock(IntPtr handle);
    [DllImport("kernel32.dll")] static extern bool GlobalUnlock(IntPtr handle);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalFree(IntPtr handle);
    [DllImport("kernel32.dll")] static extern UIntPtr GlobalSize(IntPtr handle);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int kind);
    [DllImport("kernel32.dll")] static extern uint GetFileType(IntPtr handle);
    [DllImport("user32.dll")] static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr handle);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern bool GetUserObjectInformation(IntPtr handle, int index, StringBuilder value, int length, out int needed);
    [DllImport("wtsapi32.dll")] static extern bool WTSQuerySessionInformation(IntPtr server, int session, int kind, out IntPtr buffer, out int length);
    [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr buffer);

    static void Require(bool condition) { if (!condition) throw new InvalidOperationException("clipboard_request_refused"); }
    static string Hash(byte[] value) { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(value)).Replace("-", "").ToLowerInvariant(); }
    static bool Uuid(object value) { Guid g; return value is string && Guid.TryParse((string)value, out g) && g.ToString() == (string)value; }
    static string Owner { get { return WindowsIdentity.GetCurrent().User.Value; } }
    static string PipeName(string sid) { return "hapax-clipboard-" + sid; }

    static void White(string text, ref int at) {
        while (at < text.Length && (text[at]==' ' || text[at]=='\r' || text[at]=='\n' || text[at]=='\t')) at++;
    }
    static string StringToken(string text, ref int at) {
        int start = at; Require(at < text.Length && text[at++] == '"');
        while (at < text.Length) {
            char ch = text[at++];
            if (ch == '"') return text.Substring(start, at-start);
            Require(ch >= 32);
            if (ch == '\\') { Require(at < text.Length); at++; }
        }
        Require(false); return null;
    }
    static Dictionary<string,object> Parse(byte[] raw) {
        Require(raw.Length <= MaxRequest); string text = Utf8.GetString(raw);
        var result = new Dictionary<string,object>(); int at=0; White(text,ref at);
        Require(at < text.Length && text[at++]=='{'); White(text,ref at);
        while (at < text.Length && text[at]!='}') {
            string key = Json.Deserialize<string>(StringToken(text,ref at));
            Require(key.Length <= 32 && !result.ContainsKey(key));
            White(text,ref at); Require(at < text.Length && text[at++]==':'); White(text,ref at);
            object value;
            if (at < text.Length && text[at]=='"') value = Json.Deserialize<string>(StringToken(text,ref at));
            else {
                int start=at; if (at < text.Length && text[at]=='-') at++;
                int digits=at; while(at < text.Length && text[at]>='0' && text[at]<='9') at++;
                Require(at>digits && (at-digits==1 || text[digits]!='0') && at-start<=11);
                int number; Require(Int32.TryParse(text.Substring(start,at-start),out number)); value=number;
            }
            result.Add(key,value); White(text,ref at);
            if(at < text.Length && text[at]=='}') break;
            Require(at < text.Length && text[at++]==','); White(text,ref at);
            Require(at < text.Length && text[at]!='}');
        }
        Require(at < text.Length && text[at++]=='}'); White(text,ref at); Require(at==text.Length);
        return result;
    }

    static void Active(int session) {
        Require(session != 0 && Process.GetCurrentProcess().SessionId == session);
        IntPtr state; int length;
        Require(WTSQuerySessionInformation(IntPtr.Zero, session, 8, out state, out length));
        try { Require(length >= 4 && Marshal.ReadInt32(state) == 0); } finally { WTSFreeMemory(state); }
        var desktop = OpenInputDesktop(0, false, 1); Require(desktop != IntPtr.Zero);
        try {
            var name = new StringBuilder(256); int needed;
            Require(GetUserObjectInformation(desktop, 2, name, 512, out needed) && name.ToString() == "Default");
        } finally { CloseDesktop(desktop); }
    }

    static void Put(uint format, byte[] bytes) {
        Require(format != 0);
        var memory = GlobalAlloc(0x0042, (UIntPtr)bytes.Length); Require(memory != IntPtr.Zero);
        bool transferred = false;
        try {
            var address = GlobalLock(memory); Require(address != IntPtr.Zero);
            try { Marshal.Copy(bytes, 0, address, bytes.Length); } finally { GlobalUnlock(memory); }
            Require(SetClipboardData(format, memory) != IntPtr.Zero); transferred = true;
        } finally { if (!transferred) GlobalFree(memory); }
    }

    static byte[] ClipboardRead() {
        Require(OpenClipboard(IntPtr.Zero));
        try {
            var memory = GetClipboardData(13); Require(memory != IntPtr.Zero);
            long size = (long)GlobalSize(memory).ToUInt64(); Require(size >= 2 && size <= 2L*(MaxText+1));
            var address = GlobalLock(memory); Require(address != IntPtr.Zero);
            try {
                byte[] bytes = new byte[size]; Marshal.Copy(address, bytes, 0, bytes.Length);
                int end = 0; while (end+1 < bytes.Length && (bytes[end] != 0 || bytes[end+1] != 0)) end += 2;
                Require(end+1 < bytes.Length);
                return Utf8.GetBytes(new UnicodeEncoding(false, false, true).GetString(bytes, 0, end));
            } finally { GlobalUnlock(memory); }
        } finally { CloseClipboard(); }
    }

    static bool Excluded() {
        Require(OpenClipboard(IntPtr.Zero));
        try {
            foreach (string name in new[]{"CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"}) {
                var memory = GetClipboardData(RegisterClipboardFormat(name)); Require(memory != IntPtr.Zero);
                Require(GlobalSize(memory).ToUInt64() >= 4);
                var address = GlobalLock(memory); Require(address != IntPtr.Zero);
                try { Require(Marshal.ReadInt32(address) == 0); } finally { GlobalUnlock(memory); }
            }
            return GetClipboardData(RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing")) != IntPtr.Zero;
        } finally { CloseClipboard(); }
    }

    static Dictionary<string,object> Handle(byte[] raw, string endpoint, string epoch, string owner, int session, IntPtr window) {
        var q = Parse(raw); bool set = q.ContainsKey("op") && (q["op"] as string) == "set";
        string[] keys = set ? new[]{"v","id","op","endpoint","session","epoch","bytes","sha256","data"} : new[]{"v","id","op","endpoint"};
        Require(q.Count == keys.Length); foreach (var k in keys) Require(q.ContainsKey(k));
        Require(q["v"] is int && (int)q["v"] == 1 && Uuid(q["id"]) && (q["endpoint"] as string) == endpoint);
        Require(set || (q["op"] as string) == "describe");
        Active(session);
        var reply = new Dictionary<string,object>{{"v",1},{"id",q["id"]},{"endpoint",endpoint},{"epoch",epoch},{"session",session.ToString()},{"principal",owner}};
        if (!set) return reply;
        Require((q["session"] as string) == session.ToString() && (q["epoch"] as string) == epoch);
        Require(q["bytes"] is int && (int)q["bytes"] >= 0 && (int)q["bytes"] <= MaxText && q["data"] is string);
        Require(((string)q["data"]).Length <= 1398104);
        byte[] bytes = Convert.FromBase64String((string)q["data"]);
        // Convert.FromBase64String accepts whitespace; canonical reencoding refuses it.
        Require(Convert.ToBase64String(bytes) == (string)q["data"]);
        string text = Utf8.GetString(bytes);
        Require(bytes.Length == (int)q["bytes"] && text.IndexOf('\0') < 0 && (q["sha256"] as string) == Hash(bytes));
        Active(session);
        Require(OpenClipboard(window));
        try {
            Require(EmptyClipboard());
            // Register/write exclusion before publishing text, not after the history observer.
            Put(RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing"), new byte[4]);
            Put(RegisterClipboardFormat("CanIncludeInClipboardHistory"), new byte[4]);
            Put(RegisterClipboardFormat("CanUploadToCloudClipboard"), new byte[4]);
            Put(13, Encoding.Unicode.GetBytes(text + "\0"));
        } finally { CloseClipboard(); }
        uint sequence = GetClipboardSequenceNumber();
        byte[] observed = ClipboardRead(); Active(session);
        Require(Hash(observed) == Hash(bytes) && observed.Length == bytes.Length && Excluded());
        Require(GetClipboardSequenceNumber() == sequence);
        reply.Add("bytes", observed.Length); reply.Add("sha256", Hash(observed)); reply.Add("history_excluded", true);
        return reply;
    }

    static byte[] ReadFrame(Stream stream, int maximum, DateTime deadline) {
        var header = Exact(stream, 4, deadline);
        int size = (header[0]<<24)|(header[1]<<16)|(header[2]<<8)|header[3];
        Require(size >= 0 && size <= maximum); return Exact(stream, size, deadline);
    }
    static byte[] Exact(Stream stream, int size, DateTime deadline) {
        var data = new byte[size]; int at = 0;
        while (at < size) {
            var pending = stream.BeginRead(data, at, Math.Min(8192,size-at), null, null);
            int count;
            try {
                if (!pending.AsyncWaitHandle.WaitOne(Math.Max(0, (int)(deadline-DateTime.UtcNow).TotalMilliseconds))) { stream.Dispose(); Require(false); }
                count = stream.EndRead(pending);
            } finally { pending.AsyncWaitHandle.Close(); }
            Require(count > 0); at += count;
        }
        return data;
    }
    static void WriteFrame(Stream stream, byte[] data) {
        var framed = new byte[data.Length+4]; int n = data.Length;
        framed[0]=(byte)(n>>24); framed[1]=(byte)(n>>16); framed[2]=(byte)(n>>8); framed[3]=(byte)n;
        Buffer.BlockCopy(data, 0, framed, 4, n);
        var pending = stream.BeginWrite(framed, 0, framed.Length, null, null);
        try {
            if (!pending.AsyncWaitHandle.WaitOne(8000)) { stream.Dispose(); Require(false); }
            stream.EndWrite(pending);
        } finally { pending.AsyncWaitHandle.Close(); }
    }

    public static void Server(string endpoint) {
        Require(Uuid(endpoint)); string owner = Owner, epoch = Guid.NewGuid().ToString();
        int session = Process.GetCurrentProcess().SessionId; Active(session);
        var window = CreateWindowEx(0, "STATIC", "", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        Require(window != IntPtr.Zero);
        var acl = new PipeSecurity(); acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(owner), PipeAccessRights.FullControl, AccessControlType.Allow));
        while (true) {
            using (var pipe = new NamedPipeServerStream(PipeName(owner), PipeDirection.InOut, 1,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 4096, 4096, acl)) {
                pipe.WaitForConnection();
                byte[] reply;
                try {
                    string peer = null; pipe.RunAsClient(delegate { peer = Owner; }); Require(peer == owner);
                    reply = Utf8.GetBytes(Json.Serialize(Handle(ReadFrame(pipe, MaxRequest, DateTime.UtcNow.AddSeconds(8)), endpoint, epoch, owner, session, window)));
                } catch { reply = Encoding.ASCII.GetBytes("{\"error\":\"clipboard_request_refused\"}"); }
                try { WriteFrame(pipe, reply); } catch { /* Metadata-free failure; no payload log. */ }
            }
        }
    }

    [STAThread]
    public static int Main(string[] args) {
        try {
            Require(args.Length == 1 && args[0] == "--client");
            Client(); return 0;
        } catch {
            Console.Error.WriteLine("Clipboard request refused. Next action: check enrollment and the active unlocked interactive desktop endpoint.");
            return 1;
        }
    }

    public static void Client() {
        var handle = GetStdHandle(-10);
        Require(GetFileType(handle) == 3);
        // OpenSSH supplies an overlapped named pipe. Console.OpenStandardInput uses
        // synchronous ReadFile and reproducibly stalls after one 32768-byte packet.
        // Borrow the inherited handle without taking ownership; use overlapped I/O.
        using (var input = new FileStream(new SafeFileHandle(handle, false), FileAccess.Read, 8192, true)) {
            // Framing ends the request without depending on stdin EOF.
            byte[] raw = ReadFrame(input, MaxRequest, DateTime.UtcNow.AddSeconds(8)); Parse(raw);
            using (var pipe = new NamedPipeClientStream(".", PipeName(Owner), PipeDirection.InOut,
                    PipeOptions.Asynchronous, TokenImpersonationLevel.Impersonation)) {
                pipe.Connect(6000); WriteFrame(pipe,raw);
                byte[] reply = ReadFrame(pipe,MaxReply,DateTime.UtcNow.AddSeconds(10));
                using (var output = Console.OpenStandardOutput()) { output.Write(reply,0,reply.Length); }
            }
        }
    }
}
