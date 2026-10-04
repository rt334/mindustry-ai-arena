import java.net.*;
public class T {
  public static void main(String[] a) throws Exception {
    System.out.println("preferIPv4Stack = " + System.getProperty("java.net.preferIPv4Stack"));
    System.out.println("preferIPv6Addresses = " + System.getProperty("java.net.preferIPv6Addresses"));
    DatagramSocket s = new DatagramSocket(0);
    System.out.println("?? DatagramSocket ??: " + s.getLocalSocketAddress());
    s.close();
    DatagramSocket s2 = new DatagramSocket(new InetSocketAddress("0.0.0.0", 0));
    System.out.println("?? 0.0.0.0 ??:      " + s2.getLocalSocketAddress());
    s2.close();
    System.out.println("127.0.0.1 ??: " + InetAddress.getByName("127.0.0.1"));
    System.out.println("localhost ??: " + java.util.Arrays.toString(InetAddress.getAllByName("localhost")));
  }
}
