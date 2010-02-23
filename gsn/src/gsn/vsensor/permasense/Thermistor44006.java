package gsn.vsensor.permasense;

import java.io.Serializable;
import java.text.DecimalFormat;

import org.apache.log4j.Logger;

public class Thermistor44006 implements Converter {
	
	private static final DecimalFormat decimal4 = new DecimalFormat("0.0000");
	
	private static final transient Logger logger = Logger.getLogger(Thermistor44006.class);
	
	
	public String convert(Serializable input, String value) {
		String result = null;
		double cal = 0.0;
		//long start = System.nanoTime();
		int v = ((Integer) input).intValue();
		if (v < 64000 && v != 0) {
			if (value != null)
				cal = Double.parseDouble(value);
			double ln_res = Math.log(27000.0 / ((64000.0 / v) - 1.0));
			//Math.pow(v, 3.0) needs more CPU instructions than (v * v * v)
			//double steinhart_eq = 0.00103348 + 0.000238465 * ln_res + 0.000000158948 * Math.pow(ln_res, 3);
			double steinhart_eq = 0.00103348 + (0.000238465 * ln_res) + (0.000000158948 * (ln_res * ln_res * ln_res));
			result = decimal4.format((1.0 / steinhart_eq) - 273.15 - cal);
		}
		//if (logger.isDebugEnabled())
		//	logger.debug("thermistor44006Conversion: " + Long.toString((System.nanoTime() - start) / 1000) + " us");				
		return result;
	}
	
}
