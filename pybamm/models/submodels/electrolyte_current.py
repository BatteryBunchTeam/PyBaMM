#
# Equation classes for the electrolyte current
#
from __future__ import absolute_import, division
from __future__ import print_function, unicode_literals
import pybamm

import numpy as np


class ElectrolyteCurrentBaseModel(pybamm.SubModel):
    """
    Base model for the potential and current in the electrolyte

    Parameters
    ----------
    set_of_parameters : parameter class
        The parameters to use for this submodel

    *Extends:* :class:`pybamm.SubModel`
    """

    def __init__(self, set_of_parameters):
        super().__init__(set_of_parameters)

    def get_variables(self, phi_e, i_e, eta_e_av):
        """
        Calculate dimensionless and dimensional variables for the electrolyte current
        submodel

        Parameters
        ----------
        phi_e :class:`pybamm.Concatenation`
            The electrolyte potential
        i_e :class:`pybamm.Concatenation`
            The electrolyte current density
        delta_phi_e_av: :class:`pybamm.Symbol`
            Average Ohmic losses in the electrolyte
        eta_e_av: :class:`Pybamm.Symbol`
            Average electrolyte overpotential

        Returns
        -------
        dict
            Dictionary {string: :class:`pybamm.Symbol`} of relevant variables
        """
        param = self.set_of_parameters
        pot_scale = param.potential_scale

        phi_e_n, phi_e_s, phi_e_p = phi_e.orphans

        # Set dimensionless and dimensional variables
        return {
            "Negative electrolyte potential": phi_e_n,
            "Separator electrolyte potential": phi_e_s,
            "Positive electrolyte potential": phi_e_p,
            "Electrolyte potential": phi_e,
            "Electrolyte current density": i_e,
            "Average electrolyte overpotential": eta_e_av,
            "Negative electrolyte potential [V]": -param.U_n_ref + pot_scale * phi_e_n,
            "Separator electrolyte potential [V]": -param.U_n_ref + pot_scale * phi_e_s,
            "Positive electrolyte potential [V]": -param.U_n_ref + pot_scale * phi_e_p,
            "Electrolyte potential [V]": -param.U_n_ref + pot_scale * phi_e,
            "Electrolyte current density [A m-2]": param.i_typ * i_e,
            "Average electrolyte overpotential [V]": pot_scale * eta_e_av,
        }

    def get_split_electrolyte_overpotential(self, eta_c_av, delta_phi_e_av):
        param = self.set_of_parameters
        pot_scale = param.potential_scale

        return {
            "Average concentration overpotential": eta_c_av,
            "Average electrolyte ohmic losses": delta_phi_e_av,
            "Average concentration overpotential [V]": pot_scale * eta_c_av,
            "Average electrolyte ohmic losses [V]": pot_scale * delta_phi_e_av,
        }


class MacInnesStefanMaxwell(ElectrolyteCurrentBaseModel):
    """MacInnes equation for the current in the electrolyte, derived from the
    Stefan-Maxwell equations.

    Parameters
    ----------
    set_of_parameters : parameter class
        The parameters to use for this submodel

    *Extends:* :class:`ElectrolyteCurrentBaseModel`
    """

    def __init__(self, set_of_parameters):
        super().__init__(set_of_parameters)

    def set_algebraic_system(self, phi_e, c_e, reactions, epsilon=None):
        """
        PDE system for current in the electrolyte, derived from the Stefan-Maxwell
        equations.

        Parameters
        ----------
        phi_e : :class:`pybamm.Concatenation`
            The eletrolyte potential variable
        c_e : :class:`pybamm.Concatenation`
            The eletrolyte concentration variable
        reactions : dict
            Dictionary of reaction variables
        epsilon : :class:`pybamm.Symbol`, optional
            Porosity. Default is None, in which case param.epsilon is used.
        """
        # Load parameters and spatial variables
        param = self.set_of_parameters

        # Unpack variables
        j_n = reactions["main"]["neg"]["aj"]
        j_p = reactions["main"]["pos"]["aj"]
        j = pybamm.Concatenation(j_n, pybamm.Broadcast(0, ["separator"]), j_p)

        # if porosity is not provided, use the input parameter
        if epsilon is None:
            epsilon = param.epsilon

        # functions
        i_e = (
            param.kappa_e(c_e) * (epsilon ** param.b) * param.gamma_e / param.C_e
        ) * (param.chi(c_e) * pybamm.grad(c_e) / c_e - pybamm.grad(phi_e))

        # Equations (algebraic only)
        self.algebraic = {phi_e: pybamm.div(i_e) - j}
        self.boundary_conditions = {i_e: {"left": 0, "right": 0}}
        self.initial_conditions = {phi_e: -param.U_n(param.c_n_init)}
        # no differential equations
        self.rhs = {}

        # Variables
        # average electrolyte overpotential (ohmic + concentration overpotential)
        phi_e_n, phi_e_s, phi_e_p = phi_e.orphans
        phi_e_n_av = pybamm.average(phi_e_n)
        phi_e_p_av = pybamm.average(phi_e_p)
        eta_e_av = phi_e_p_av - phi_e_n_av

        self.variables = self.get_variables(phi_e, i_e, eta_e_av)

        # Set default solver to DAE
        self.default_solver = pybamm.ScikitsDaeSolver()

    def get_explicit_leading_order(self, ocp_n, eta_r_n):
        """
        Provides explicit leading order solution to the electrolyte current conservation
        equation where the constitutive equation is taken to be of Stefan-Maxwell form.

        Parameters
        ----------
        ocp_n : :class:`pybamm.Symbol`
            Open-circuit potential in the negative electrode
        eta_r_n : :class:`pybamm.Symbol`
            Reaction overpotential in the negative electrode

        Returns
        -------
        dict
            Dictionary {string: :class:`pybamm.Symbol`} of relevant variables
        """
        # import parameters and spatial variables
        param = self.set_of_parameters
        l_n = param.l_n
        l_p = param.l_p
        x_n = pybamm.standard_spatial_vars.x_n
        x_p = pybamm.standard_spatial_vars.x_p

        # define current
        i_cell = param.current_with_time

        # electrolye potential
        phi_e_const = -ocp_n - eta_r_n
        phi_e_n = pybamm.Broadcast(phi_e_const, ["negative electrode"])
        phi_e_s = pybamm.Broadcast(phi_e_const, ["separator"])
        phi_e_p = pybamm.Broadcast(phi_e_const, ["positive electrode"])
        phi_e = pybamm.Concatenation(phi_e_n, phi_e_s, phi_e_p)

        # electrolyte current
        i_e_n = i_cell * x_n / l_n
        i_e_s = pybamm.Broadcast(i_cell, ["separator"])
        i_e_p = i_cell * (1 - x_p) / l_p
        i_e = pybamm.Concatenation(i_e_n, i_e_s, i_e_p)

        # electrolyte ohmic losses
        delta_phi_e_av = pybamm.Scalar(0)
        # concentration overpotential
        eta_c_av = pybamm.Scalar(0)
        # electrolyte overpotential
        eta_e_av = eta_c_av + delta_phi_e_av

        variables = self.get_variables(phi_e, i_e, eta_e_av)
        additional_vars = self.get_split_electrolyte_overpotential(
            eta_c_av, delta_phi_e_av
        )
        variables.update(additional_vars)

        return variables

    def get_explicit_combined(
        self, ocp_n, eta_r_n, c_e, phi_s_n, epsilon=None, c_e_0=None
    ):
        """
        Provides and explicit combined leading and first order solution to the
        electrolyte current conservation equation where the constitutive equation is
        taken to be of Stefan-Maxwell form. Note that the returned current density is
        only the leading order approximation.

        Parameters
        ----------
        ocp_n : :class:`pybamm.Symbol`
            Open-circuit potential in the negative electrode
        eta_r_n : :class:`pybamm.Symbol`
            Reaction overpotential in the negative electrode
        c_e : :class:`pybamm.Concatenation`
            The electrolyte concentration variable
        phi_s_n : :class:`pybamm.Symbol`
            The negative electrode potential
        epsilon : :class:`pybamm.Symbol`, optional
            Porosity. Default is None, in which case param.epsilon is used.
        c_e : :class:`pybamm.Concatenation`
            Leading-order concentration

        Returns
        -------
        dict
            Dictionary {string: :class:`pybamm.Symbol`} of relevant variables
        """
        # import parameters and spatial variables
        param = self.set_of_parameters
        l_n = param.l_n
        l_p = param.l_p
        i_cell = param.current_with_time
        x_n = pybamm.standard_spatial_vars.x_n
        x_s = pybamm.standard_spatial_vars.x_s
        x_p = pybamm.standard_spatial_vars.x_p

        # extract c_e components
        c_e_n, c_e_s, c_e_p = c_e.orphans

        # if porosity is not provided, use the input parameter
        if epsilon is None:
            epsilon = param.epsilon
        if c_e_0 is None:
            c_e_0 = pybamm.Scalar(1)
        eps_n, eps_s, eps_p = [e.orphans[0] for e in epsilon.orphans]

        # bulk conductivities (leading order)
        kappa_n = param.kappa_e(c_e_0) * eps_n ** param.b
        kappa_s = param.kappa_e(c_e_0) * eps_s ** param.b
        kappa_p = param.kappa_e(c_e_0) * eps_p ** param.b

        # get electrode averaged values
        ocp_n_av = pybamm.average(ocp_n)
        eta_r_n_av = pybamm.average(eta_r_n)
        phi_s_n_av = pybamm.average(phi_s_n)

        # electrolyte current (leading-order approximation)
        i_e_n = i_cell * x_n / l_n
        i_e_s = pybamm.Broadcast(i_cell, ["separator"])
        i_e_p = i_cell * (1 - x_p) / l_p
        i_e = pybamm.Concatenation(i_e_n, i_e_s, i_e_p)

        # electrolyte potential (combined leading and first order)
        phi_e_const = (
            -ocp_n_av
            - eta_r_n_av
            + phi_s_n_av
            - 2
            * (1 - param.t_plus)
            * pybamm.average(pybamm.Function(np.log, c_e_n / c_e_0))
            - i_cell
            * param.C_e
            * l_n
            / param.gamma_e
            * (1 / (3 * kappa_n) - 1 / kappa_s)
        )

        phi_e_n = (
            phi_e_const
            + 2 * (1 - param.t_plus) * pybamm.Function(np.log, c_e_n / c_e_0)
            - (i_cell * param.C_e / param.gamma_e)
            * ((x_n ** 2 - l_n ** 2) / (2 * kappa_n * l_n) + l_n / kappa_s)
        )

        phi_e_s = (
            phi_e_const
            + 2 * (1 - param.t_plus) * pybamm.Function(np.log, c_e_s / c_e_0)
            - (i_cell * param.C_e / param.gamma_e) * (x_s / kappa_s)
        )

        phi_e_p = (
            phi_e_const
            + 2 * (1 - param.t_plus) * pybamm.Function(np.log, c_e_p / c_e_0)
            - (i_cell * param.C_e / param.gamma_e)
            * (
                (x_p * (2 - x_p) + l_p ** 2 - 1) / (2 * kappa_p * l_p)
                + (1 - l_p) / kappa_s
            )
        )

        phi_e = pybamm.Concatenation(phi_e_n, phi_e_s, phi_e_p)

        "Ohmic losses and overpotentials"
        # average electrolyte ohmic losses
        delta_phi_e_av = -(param.C_e * i_cell / param.gamma_e) * (
            param.l_n / (3 * kappa_n)
            + param.l_s / (kappa_s)
            + param.l_p / (3 * kappa_p)
        )

        # concentration overpotential (combined leading and first order)
        eta_c_av = (
            2
            * (1 - param.t_plus)
            * (
                pybamm.average(pybamm.Function(np.log, c_e_p / c_e_0))
                - pybamm.average(pybamm.Function(np.log, c_e_n / c_e_0))
            )
        )

        # electrolyte overpotential
        eta_e_av = eta_c_av + delta_phi_e_av

        # get variables
        variables = self.get_variables(phi_e, i_e, eta_e_av)
        additional_vars = self.get_split_electrolyte_overpotential(
            eta_c_av, delta_phi_e_av
        )

        variables.update(additional_vars)

        return variables